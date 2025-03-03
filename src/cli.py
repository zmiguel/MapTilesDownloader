#!/usr/bin/env python

import argparse
import os
import sys
import json
import time
import logging
import math
from urllib.parse import urlparse
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
import logging.handlers

from utils import Utils
from file_writer import FileWriter
from mbtiles_writer import MbtilesWriter
from repo_writer import RepoWriter

# Configure logging
def setup_logging(verbose=False, log_file=None):
    """Set up logging configuration based on verbosity level"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create formatters
    detailed_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    simple_formatter = logging.Formatter('%(message)s')

    # Console handler with reduced output
    console = logging.StreamHandler()
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    console.setFormatter(simple_formatter)
    root_logger.addHandler(console)

    # File handler for detailed logs if specified
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)

    # Configure specific loggers
    utils_logger = logging.getLogger('tile-downloader')
    utils_logger.setLevel(logging.INFO if verbose else logging.WARNING)

    cli_logger = logging.getLogger('tile-downloader-cli')
    return cli_logger

logger = setup_logging()

def parse_bounds(bounds_str):
    """Parse bounds from a string like 'min_lon,min_lat,max_lon,max_lat'"""
    try:
        parts = [float(x) for x in bounds_str.split(',')]
        if len(parts) != 4:
            raise ValueError("Bounds must have exactly 4 values")
        return parts
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid bounds format: {str(e)}")

def load_geojson(filename):
    """Load a GeoJSON file and validate that it contains a polygon"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)

        # Basic validation
        if data.get('type') != 'FeatureCollection' and not (data.get('type') == 'Feature' and
                                                           data.get('geometry', {}).get('type') in ('Polygon', 'MultiPolygon')):
            raise ValueError("GeoJSON file must contain a Feature with Polygon or MultiPolygon geometry")

        return data
    except (json.JSONDecodeError, ValueError) as e:
        raise argparse.ArgumentTypeError(f"Invalid GeoJSON file: {str(e)}")
    except FileNotFoundError:
        raise argparse.ArgumentTypeError(f"GeoJSON file not found: {filename}")

def get_writer_by_type(output_type):
    """Return the appropriate writer class based on output type"""
    if output_type == "mbtiles":
        return MbtilesWriter
    elif output_type == "repo":
        return RepoWriter
    else:  # default to directory
        return FileWriter

def calculate_tiles(min_lon, min_lat, max_lon, max_lat, min_zoom, max_zoom, geojson=None):
    """Calculate tiles within bounds for all zoom levels"""
    import shapely.geometry
    from shapely.prepared import prep

    all_tiles = []

    # If we have a GeoJSON, create a shapely geometry from it
    polygon = None
    if geojson:
        if geojson.get('type') == 'FeatureCollection':
            features = geojson.get('features', [])
            if not features:
                raise ValueError("Empty FeatureCollection in GeoJSON")
            # Use the first feature that's a polygon
            for feature in features:
                geom = feature.get('geometry', {})
                if geom.get('type') in ('Polygon', 'MultiPolygon'):
                    polygon = shapely.geometry.shape(geom)
                    break
            if polygon is None:
                raise ValueError("No polygon/multipolygon found in GeoJSON features")
        else:
            geom = geojson.get('geometry', {})
            if geom.get('type') in ('Polygon', 'MultiPolygon'):
                polygon = shapely.geometry.shape(geom)
            else:
                raise ValueError("GeoJSON feature must have Polygon or MultiPolygon geometry")

        # Create a prepared polygon for faster operations
        prepared_polygon = prep(polygon)

    # Helper functions to calculate tile coordinates
    def lon_to_x(lon, zoom):
        return int((lon + 180) / 360 * (2 ** zoom))

    def lat_to_y(lat, zoom):
        return int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * (2 ** zoom))

    def x_to_lon(x, zoom):
        return x / (2 ** zoom) * 360 - 180

    def y_to_lat(y, zoom):
        n = math.pi - 2 * math.pi * y / (2 ** zoom)
        return math.degrees(math.atan(math.sinh(n)))

    # Calculate tiles for each zoom level
    for zoom in range(min_zoom, max_zoom + 1):
        # Calculate tile boundaries
        min_x = lon_to_x(min_lon, zoom)
        max_x = lon_to_x(max_lon, zoom)
        min_y = lat_to_y(max_lat, zoom)  # Note: y is inverted
        max_y = lat_to_y(min_lat, zoom)

        # Loop through all tiles in the bounding box
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                # If we have a polygon, check if the tile intersects it
                if polygon:
                    # Calculate the tile's bounding box
                    tile_min_lon = x_to_lon(x, zoom)
                    tile_max_lon = x_to_lon(x + 1, zoom)
                    tile_min_lat = y_to_lat(y + 1, zoom)
                    tile_max_lat = y_to_lat(y, zoom)

                    # Create a polygon representing the tile
                    tile_polygon = shapely.geometry.box(tile_min_lon, tile_min_lat, tile_max_lon, tile_max_lat)

                    # Only add the tile if it intersects with our polygon
                    if prepared_polygon.intersects(tile_polygon):
                        all_tiles.append((x, y, zoom))
                else:
                    # Without a polygon, include all tiles in the bounding box
                    all_tiles.append((x, y, zoom))

    return all_tiles

def download_tile(args):
    """Download a single tile"""
    x, y, z, url, output_dir, output_file, output_type, output_scale, verbose, max_retries, timeout, retry_delay = args

    # Create a dummy lock for thread safety
    class DummyLock:
        def acquire(self): pass
        def release(self): pass

    dummy_lock = DummyLock()

    try:
        # Create the actual file path - prepend "output" to match server.py
        file_path = os.path.join("output", output_dir, output_file)

        # Replace template parameters
        file_path = file_path.replace("{x}", str(x))
        file_path = file_path.replace("{y}", str(y))
        file_path = file_path.replace("{z}", str(z))
        file_path = file_path.replace("{quad}", Utils.tileXYToQuadKey(x, y, z) if hasattr(Utils, 'tileXYToQuadKey') else "")

        # Check if file already exists
        writer = get_writer_by_type(output_type)
        if writer.exists(file_path, x, y, z):
            return f"Tile {x},{y},{z} already exists"

        # Make sure temp directory exists before creating temp file
        temp_dir = os.path.join("temp")
        os.makedirs(temp_dir, exist_ok=True)

        # Create a temporary file name
        temp_file = os.path.join(temp_dir, Utils.randomString() + ".png")

        # Download the tile with improved retry mechanism
        result_code = Utils.downloadFileScaled(
            url,
            temp_file,
            x, y, z,
            output_scale,
            max_retries=max_retries,
            timeout=timeout,
            retry_delay=retry_delay
        )

        # Check if download was successful AND file exists
        if result_code == 200 and os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            # Add the tile to the output
            writer.addTile(dummy_lock, file_path, temp_file, x, y, z, output_scale)

            # Clean up the temp file
            try:
                os.remove(temp_file)
            except (OSError, IOError) as e:
                logger.warning(f"Failed to remove temp file {temp_file}: {str(e)}")
                # Continue even if we couldn't delete the temp file

            # Don't return verbose message when in quiet mode
            if verbose:
                return f"Downloaded tile {x},{y},{z}"
            else:
                return None
        else:
            # The file should exist if result_code is 200, so this is an error condition
            if result_code == 200 and not os.path.exists(temp_file):
                return f"Error downloading tile {x},{y},{z}: Temp file not created despite successful code"
            elif result_code == 200 and os.path.getsize(temp_file) == 0:
                return f"Error downloading tile {x},{y},{z}: Empty file downloaded"
            else:
                # Always return errors regardless of verbosity
                return f"Failed to download tile {x},{y},{z} (code: {result_code})"

    except (OSError, IOError) as e:
        # Handle file system errors
        return f"File error for tile {x},{y},{z}: {str(e)}"
    except Exception as e:
        # Catch any other errors to prevent the entire process from crashing
        return f"Unexpected error for tile {x},{y},{z}: {str(e)}"

def run_server(port=8080):
    """Run the web server"""
    from server import run
    os.environ['TILE_DOWNLOADER_PORT'] = str(port)
    run()

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description='Tile Downloader CLI')
    subparsers = parser.add_subparsers(dest='command')

    # Server command
    server_parser = subparsers.add_parser('server', help='Run the web server')
    server_parser.add_argument('--port', type=int, default=8080, help='Server port')

    # Download command
    download_parser = subparsers.add_parser('download', help='Download tiles directly')
    download_parser.add_argument('--url', required=True, help='Tile URL template with {x}, {y}, {z}, or {quad} placeholders')
    download_parser.add_argument('--output-dir', required=True, help='Output directory')
    download_parser.add_argument('--min-zoom', type=int, required=True, help='Minimum zoom level')
    download_parser.add_argument('--max-zoom', type=int, required=True, help='Maximum zoom level')
    download_parser.add_argument('--threads', type=int, default=4, help='Number of parallel download threads')
    download_parser.add_argument('--output-type', choices=['directory', 'mbtiles', 'repo'], default='directory',
                      help='Output type (directory, mbtiles, or repo)')
    download_parser.add_argument('--output-file', default="{z}/{x}/{y}.png",
                      help='Output file pattern (for directory type) or filename (for mbtiles/repo)')
    download_parser.add_argument('--output-scale', type=int, choices=[1, 2], default=1,
                      help='Output scale (1x or 2x)')

    # Add verbosity and log file options
    download_parser.add_argument('--verbose', '-v', action='store_true',
                      help='Enable verbose output')
    download_parser.add_argument('--log-file',
                      help='Log file for detailed messages (default: none)')

    # Add retry configuration options
    download_parser.add_argument('--max-retries', type=int, default=5,
                      help='Maximum retry attempts per tile (default: 5)')
    download_parser.add_argument('--timeout', type=int, default=60,
                      help='Request timeout in seconds (default: 60)')
    download_parser.add_argument('--retry-delay', type=int, default=2,
                      help='Initial retry delay in seconds (default: 2, will increase exponentially)')

    # Add new CLI options
    download_parser.add_argument('--rate-limit-delay', type=float, default=0,
                      help='Add delay between downloads in seconds (default: 0, try 0.1-0.5 for rate limited servers)')

    # Either bounds or geojson must be specified
    group = download_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--bounds', type=parse_bounds,
                      help='Bounding box as min_lon,min_lat,max_lon,max_lat')
    group.add_argument('--geojson', type=load_geojson,
                      help='GeoJSON file containing a polygon area to download')

    args = parser.parse_args()

    if args.command == 'server':
        run_server(args.port)

    elif args.command == 'download':
        try:
            # Setup logging based on verbosity
            logger = setup_logging(args.verbose, args.log_file)

            # Create necessary directories - include the 'output' directory
            os.makedirs("temp", exist_ok=True)
            os.makedirs("output", exist_ok=True)  # Create base output directory
            os.makedirs(os.path.join("output", args.output_dir), exist_ok=True)  # Create user output dir inside 'output'

            # Create a dummy lock for thread safety
            class DummyLock:
                def acquire(self): pass
                def release(self): pass

            dummy_lock = DummyLock()

            start_time = time.time()
            print(f"Calculating tiles for zoom levels {args.min_zoom} to {args.max_zoom}...")

            # Calculate tiles based on bounds or geojson
            if args.bounds:
                min_lon, min_lat, max_lon, max_lat = args.bounds
                tiles = calculate_tiles(min_lon, min_lat, max_lon, max_lat,
                                    args.min_zoom, args.max_zoom, None)
            else:
                # Get bounds from geojson for metadata
                from shapely.geometry import shape

                if args.geojson.get('type') == 'FeatureCollection':
                    # Use first feature with a geometry
                    for feature in args.geojson.get('features', []):
                        if feature.get('geometry'):
                            geom = shape(feature['geometry'])
                            min_lon, min_lat, max_lon, max_lat = geom.bounds
                            break
                else:
                    geom = shape(args.geojson.get('geometry', {}))
                    min_lon, min_lat, max_lon, max_lat = geom.bounds

                tiles = calculate_tiles(min_lon, min_lat, max_lon, max_lat,
                                        args.min_zoom, args.max_zoom, args.geojson)

            print(f"Found {len(tiles)} tiles to download")

            # Initialize metadata if using mbtiles or repo
            if args.output_type in ('mbtiles', 'repo'):
                writer = get_writer_by_type(args.output_type)
                center_lon = (min_lon + max_lon) / 2
                center_lat = (min_lat + max_lat) / 2
                center_zoom = (args.min_zoom + args.max_zoom) // 2

                output_file = args.output_file
                if "{x}" in output_file or "{y}" in output_file or "{z}" in output_file:
                    if args.output_type == 'mbtiles':
                        output_file = "tiles.mbtiles"
                    else:
                        output_file = "tiles.repo"
                    print(f"Warning: Output file contains placeholders but {args.output_type} requires a static filename. Using {output_file}.")

                # Fix path to include 'output' directory prefix
                output_path = os.path.join("output", args.output_dir)
                full_path = os.path.join(output_path, output_file)

                # Use dummy_lock instead of None
                writer.addMetadata(dummy_lock, output_path, full_path, output_file,
                                "Tile Downloader CLI", "png",
                                [min_lon, min_lat, max_lon, max_lat],
                                [center_lon, center_lat, center_zoom],
                                args.min_zoom, args.max_zoom,
                                "mercator", 256 * args.output_scale)

            # Download tiles in parallel with rate limiting if specified
            download_args = [
                (x, y, z, args.url, args.output_dir, args.output_file, args.output_type, args.output_scale,
                args.verbose, args.max_retries, args.timeout, args.retry_delay)
                for x, y, z in tiles
            ]

            print(f"Starting download with {args.threads} threads...")
            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                # Use tqdm with better handling of external writes
                progress_bar = tqdm(
                    total=len(download_args),
                    dynamic_ncols=True,  # Adapt to terminal size changes
                    smoothing=0.1,       # Smoother progress updates
                    unit='tile',         # Show progress in 'tiles'
                    miniters=1,          # Update at least every iteration
                    position=0,          # Keep at position 0 (bottom)
                    leave=True           # Leave progress bar after completion
                )

                try:
                    # Implement rate limiting between downloads if specified
                    if args.rate_limit_delay > 0:
                        for i, result in enumerate(executor.map(download_tile, download_args)):
                            progress_bar.update(1)
                            if result:  # Only output if there's something to say
                                if args.verbose:
                                    progress_bar.write(result)
                                elif "Failed" in result or "Error" in result:  # Always show errors
                                    progress_bar.write(result)

                            # Add delay between tile downloads to avoid rate limiting
                            if i < len(download_args) - 1:  # Don't delay after the last download
                                time.sleep(args.rate_limit_delay)
                    else:
                        # Process without delay
                        for result in executor.map(download_tile, download_args):
                            progress_bar.update(1)
                            if result:  # Only output if there's something to say
                                if args.verbose:
                                    progress_bar.write(result)
                                elif "Failed" in result or "Error" in result:  # Always show errors
                                    progress_bar.write(result)
                except Exception as e:
                    progress_bar.write(f"Error in download process: {str(e)}")
                    # Continue with cleanup even if there's an error

                progress_bar.close()

            # Finalize metadata
            if args.output_type in ('mbtiles', 'repo'):
                writer = get_writer_by_type(args.output_type)
                output_file = args.output_file
                if "{x}" in output_file or "{y}" in output_file or "{z}" in output_file:
                    if args.output_type == 'mbtiles':
                        output_file = "tiles.mbtiles"
                    else:
                        output_file = "tiles.repo"

                # Fix path to include 'output' directory prefix
                output_path = os.path.join("output", args.output_dir)
                full_path = os.path.join(output_path, output_file)

                # Use dummy_lock instead of None
                writer.close(dummy_lock, output_path, full_path, args.min_zoom, args.max_zoom)

            elapsed = time.time() - start_time
            print(f"Download complete! {len(tiles)} tiles downloaded in {elapsed:.2f} seconds")

        except Exception as e:
            print(f"Error during download process: {str(e)}")
            sys.exit(1)

    else:
        parser.print_help()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
