# Tile Downloader

A utility for downloading map tiles from various tile services.

<p align="center">
  <img src="gif/map-tiles-downloader.gif">
</p>

## Features

- Download tiles for a specific region and zoom levels
- **Draw custom polygons** for precise area selection (great for coastal regions)
- **Export drawn areas as GeoJSON** for use with the CLI tool
- Save tiles in different formats (file directory, MBTiles, repo)
- **Powerful CLI interface** for automated and headless downloads
- Web UI for visual tile selection
- **Robust retry mechanism** for handling network issues
- Multi-threading to download tiles in parallel
- Cross platform, use any OS as long as it has Python and a browser
- Support for Docker containers
- Supports 2x/Hi-Res/Retina/512x512 tiles by merging multiple tiles
- Ability to ignore tiles already downloaded
- Specify any custom file name format
- Supports ANY tile provider as long as the URL has `x`, `y`, `z`, or `quad` in it
- Built using MapBox 💗

## Requirements

- Python 3.13+
- Install dependencies: `pip install -r requirements.txt`

## Installation

### Using Docker

Docker is a pretty simple way to install and contain applications. [Install Docker on your system](https://www.docker.com/products/docker-desktop), and paste this on your command line:

```sh
docker run -v $PWD/output:/app/output/ -p 8080:8080 -it aliashraf/map-tiles-downloader
```

To use your own Mapbox access token (recommended for production use):

```sh
docker run -v $PWD/output:/app/output/ -p 8080:8080 -e MAPBOX_ACCESS_TOKEN=your_mapbox_token_here -it aliashraf/map-tiles-downloader
```

Now open the browser and head over to `http://localhost:8080`. The downloaded maps will be stored in the `output` directory.

## So what does it do?

This tiny python based script allows you to download map tiles from Google, Bing, Open Street Maps, ESRI, NASA, and other providers. This script comes with an easy to use web based map UI for selecting the area and previewing tiles.

**Just run the script via command line**

```sh
python server.py
```

Then open up your web browser and navigate to `http://localhost:8080`. The output map tiles will be in the `output\{timestamp}\` directory by default.

## Using the CLI Tool

Tile Downloader includes a powerful command-line interface for automated downloading of tiles without using the web UI.

### Basic Usage

```sh
# Run the web server
python cli.py server --port 8080

# Download tiles using bounds
python cli.py download --url "https://tile.openstreetmap.org/{z}/{x}/{y}.png" \
  --output-dir "my-map" --min-zoom 10 --max-zoom 12 \
  --bounds -74.02,40.70,-73.95,40.75

# Download tiles using a GeoJSON polygon
python cli.py download --url "https://tile.openstreetmap.org/{z}/{x}/{y}.png" \
  --output-dir "my-map" --min-zoom 10 --max-zoom 12 \
  --geojson my-area.geojson
```

### Command Reference

#### Server Command

```sh
python cli.py server [--port PORT]
```

- `--port PORT`: Server port (default: 8080)

#### Download Command

```sh
python cli.py download [OPTIONS]
```

Required parameters:
- `--url URL`: Tile URL template with {x}, {y}, {z}, or {quad} placeholders
- `--output-dir DIR`: Output directory (inside the `output` folder)
- `--min-zoom ZOOM`: Minimum zoom level to download
- `--max-zoom ZOOM`: Maximum zoom level to download
- Either `--bounds` or `--geojson` must be specified:
  - `--bounds min_lon,min_lat,max_lon,max_lat`: Bounding box coordinates
  - `--geojson FILE`: GeoJSON file containing a polygon area to download

Optional parameters:
- `--threads N`: Number of parallel download threads (default: 4)
- `--output-type TYPE`: Output type: directory, mbtiles, or repo (default: directory)
- `--output-file PATTERN`: Output file pattern or name (default: "{z}/{x}/{y}.png")
- `--output-scale SCALE`: Output scale: 1 or 2 (default: 1)
- `--verbose, -v`: Enable verbose output
- `--log-file FILE`: Log file for detailed messages
- `--max-retries N`: Maximum retry attempts per tile (default: 5)
- `--timeout SEC`: Request timeout in seconds (default: 60)
- `--retry-delay SEC`: Initial retry delay in seconds (default: 2)
- `--rate-limit-delay SEC`: Add delay between downloads to avoid rate limits (default: 0)

### Examples

#### Basic tile download with bounding box:

```sh
python cli.py download --url "https://tile.openstreetmap.org/{z}/{x}/{y}.png" \
  --output-dir "osm-nyc" --min-zoom 12 --max-zoom 15 \
  --bounds -74.02,40.70,-73.95,40.75
```

#### Download using GeoJSON with MBTiles output:

```sh
python cli.py download --url "https://tile.openstreetmap.org/{z}/{x}/{y}.png" \
  --output-dir "osm-custom-area" --min-zoom 10 --max-zoom 14 \
  --geojson area.geojson --output-type mbtiles --output-file "tiles.mbtiles"
```

#### Handle rate-limited servers:

```sh
python cli.py download --url "https://example.com/tiles/{z}/{x}/{y}.png" \
  --output-dir "rate-limited" --min-zoom 10 --max-zoom 12 \
  --bounds -10,30,10,40 --threads 2 --rate-limit-delay 0.5 \
  --max-retries 8 --retry-delay 5
```

#### Using quadkey notation (for Bing Maps):

```sh
python cli.py download --url "http://ecn.t0.tiles.virtualearth.net/tiles/a{quad}.jpeg?g=129" \
  --output-dir "bing-map" --min-zoom 10 --max-zoom 15 \
  --bounds -122.4,37.7,-122.3,37.8
```

### Using GeoJSON from the Web UI

You can draw an area in the web UI and export it as GeoJSON, then use that file with the CLI tool:

1. Open the web UI at http://localhost:8080
2. Draw a polygon or rectangle on the map
3. Click "Export GeoJSON" and save the file
4. Use that file with the CLI:
   ```sh
   python cli.py download --url "https://tile.openstreetmap.org/{z}/{x}/{y}.png" \
     --output-dir "web-selection" --min-zoom 10 --max-zoom 15 \
     --geojson exported-area.geojson
   ```

## Purpose

I design map related things as a hobby, and often I have to work with offline maps that require tiles to be stored on my local system. Downloading tiles is a bit of a headache, and the current solutions have user experience issues. So I built this tiny script in a couple of hours to speed up my work.

## Important Disclaimer

Downloading map tiles is subject to the terms and conditions of the tile provider. Some providers such as Google Maps have restrictions in place to avoid abuse, therefore before downloading any tiles make sure you understand their TOCs. I recommend not using Google, Bing, and ESRI tiles in any commercial application without their consent.

## Troubleshooting

### Connection Reset Errors

If you're seeing `ConnectionResetError` or `Connection reset by peer` errors, this typically means the tile server is enforcing rate limits or dropping connections. Try these solutions:

1. **Add a delay between requests**: Use the `--rate-limit-delay` parameter with the CLI:
   ```sh
   python cli.py download --url "..." --rate-limit-delay 0.5 ...
   ```

2. **Reduce parallel threads**: Use fewer concurrent connections:
   ```sh
   python cli.py download --url "..." --threads 2 ...
   ```

3. **Increase retry settings**:
   ```sh
   python cli.py download --url "..." --max-retries 10 --retry-delay 5 ...
   ```

4. **Try a different tile provider**: Some providers have stricter rate limits than others.

### File Not Found or Temporary File Errors

If you encounter `No such file or directory` errors for temporary files:

1. **Ensure the required directories exist**: The program should create `temp` and `output` directories, but you can create them manually if needed:
   ```sh
   mkdir -p temp output
   ```

2. **Check disk permissions**: Make sure your user has write permissions for these directories

3. **Check disk space**: Ensure you have enough space available for downloaded tiles

4. **Clean temp directory**: Sometimes stale temporary files can cause issues:
   ```sh
   rm -rf temp/* && mkdir -p temp
   ```

## Environment Variables

The application supports the following environment variables:

- `MAPBOX_ACCESS_TOKEN`: Your Mapbox API access token for rendering maps in the web UI.
  If not provided, a default public token is used with limited functionality.

  To obtain your own token:
  1. Sign up at [Mapbox](https://www.mapbox.com/)
  2. Navigate to your account's Access Tokens page
  3. Create a token with the necessary scopes
  4. Pass the token to the application:
     ```sh
     # When running directly
     export MAPBOX_ACCESS_TOKEN=your_token_here
     python server.py

     # When using Docker
     docker run -e MAPBOX_ACCESS_TOKEN=your_token_here -p 8080:8080 ghcr.io/zmiguel/map-tiles-downloader
     ```

## License

This software is released under the [MIT License](LICENSE). Please read LICENSE for information on the
software availability and distribution.

Original Copyright (c) 2020 [Ali Ashraf](http://aliashraf.net)
Enhanced version Copyright (c) 2025 [José Valdiviesso](https://github.com/zmiguel)

This program contains improvements written by AI (Claude 3.7 Sonnet Thinking).