#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import threading

from urllib.parse import urlparse
import cgi
import uuid
import json
import os
import base64
import mimetypes
import sys
import logging

from file_writer import FileWriter
from mbtiles_writer import MbtilesWriter
from repo_writer import RepoWriter
from utils import Utils

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('tile-server')

lock = threading.Lock()

# Configure download parameters - can be moved to a config file later
DOWNLOAD_MAX_RETRIES = 5
DOWNLOAD_TIMEOUT = 60  # seconds
DOWNLOAD_RETRY_DELAY = 1  # seconds

# Default token to use if environment variable is not set
DEFAULT_MAPBOX_TOKEN = ""

class serverHandler(BaseHTTPRequestHandler):
    # Add a timeout to prevent hanging connections
    timeout = 120  # 2 minutes timeout

    def log_error(self, format, *args):
        """Override to use the logger instead of stderr"""
        logger.error(format % args)

    def log_message(self, format, *args):
        """Override to use the logger instead of stderr"""
        logger.info(format % args)

    def randomString(self):
        return uuid.uuid4().hex.upper()[0:6]

    def writerByType(self, type):
        if(type == "mbtiles"):
            return MbtilesWriter
        elif(type == "repo"):
            return RepoWriter
        elif(type == "directory"):
            return FileWriter

    def send_json_response(self, result):
        """Safely send a JSON response, handling potential broken pipe errors"""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")  # Close connection after response
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
        except BrokenPipeError:
            # Client disconnected, log it and suppress the error
            logger.warning("Client disconnected while sending response")
            return
        except ConnectionResetError:
            logger.warning("Connection reset by client")
            return
        except Exception as e:
            logger.error(f"Error sending response: {str(e)}")
            return

    def do_POST(self):
        try:
            # First check if the client is still connected
            if self.client_address is None:
                logger.warning("Client already disconnected before processing request")
                return

            ctype, pdict = cgi.parse_header(self.headers.get('Content-Type'))
            pdict['boundary'] = bytes(pdict['boundary'], "utf-8")

            content_len = int(self.headers.get('Content-length'))
            pdict['CONTENT-LENGTH'] = content_len

            postvars = cgi.parse_multipart(self.rfile, pdict)

            parts = urlparse(self.path)
            if parts.path == '/download-tile':
                # Process the download tile request
                # ...existing code...

                # Use a try-finally block to ensure resource cleanup
                tempFilePath = None
                try:
                    x = int(postvars['x'][0])
                    y = int(postvars['y'][0])
                    z = int(postvars['z'][0])
                    quad = str(postvars['quad'][0])
                    timestamp = int(postvars['timestamp'][0])
                    outputDirectory = str(postvars['outputDirectory'][0])
                    outputFile = str(postvars['outputFile'][0])
                    outputType = str(postvars['outputType'][0])
                    outputScale = int(postvars['outputScale'][0])
                    source = str(postvars['source'][0])

                    replaceMap = {
                        "x": str(x),
                        "y": str(y),
                        "z": str(z),
                        "quad": quad,
                        "timestamp": str(timestamp),
                    }

                    for key, value in replaceMap.items():
                        newKey = str("{" + str(key) + "}")
                        outputDirectory = outputDirectory.replace(newKey, value)
                        outputFile = outputFile.replace(newKey, value)

                    result = {}

                    filePath = os.path.join("output", outputDirectory, outputFile)

                    if self.writerByType(outputType).exists(filePath, x, y, z):
                        result["code"] = 200
                        result["message"] = 'Tile already exists'
                        logger.info(f"Tile exists: {filePath}")
                    else:
                        tempFile = self.randomString() + ".png"
                        tempFilePath = os.path.join("temp", tempFile)

                        # Ensure temp directory exists
                        os.makedirs(os.path.dirname(tempFilePath), exist_ok=True)

                        # Use the improved download function with retry and timeout parameters
                        result["code"] = Utils.downloadFileScaled(
                            source,
                            tempFilePath,
                            x, y, z,
                            outputScale,
                            max_retries=DOWNLOAD_MAX_RETRIES,
                            timeout=DOWNLOAD_TIMEOUT,
                            retry_delay=DOWNLOAD_RETRY_DELAY
                        )

                        source_str = source.replace("{x}", str(x)).replace("{y}", str(y)).replace("{z}", str(z))
                        logger.info(f"Download result for {source_str}: {result['code']}")

                        if os.path.isfile(tempFilePath):
                            self.writerByType(outputType).addTile(lock, filePath, tempFilePath, x, y, z, outputScale)

                            with open(tempFilePath, "rb") as image_file:
                                result["image"] = base64.b64encode(image_file.read()).decode("utf-8")

                            result["message"] = 'Tile Downloaded'
                            logger.info(f"Saved tile: {filePath}")
                        else:
                            result["message"] = 'Download failed'
                            logger.warning(f"Download failed for tile: x={x}, y={y}, z={z}")

                    self.send_json_response(result)

                finally:
                    # Clean up temp file if it exists
                    if tempFilePath and os.path.exists(tempFilePath):
                        try:
                            os.remove(tempFilePath)
                        except Exception as e:
                            logger.error(f"Error removing temp file: {str(e)}")

            elif parts.path == '/start-download':
                outputType = str(postvars['outputType'][0])
                outputScale = int(postvars['outputScale'][0])
                outputDirectory = str(postvars['outputDirectory'][0])
                outputFile = str(postvars['outputFile'][0])
                minZoom = int(postvars['minZoom'][0])
                maxZoom = int(postvars['maxZoom'][0])
                timestamp = int(postvars['timestamp'][0])
                bounds = str(postvars['bounds'][0])
                boundsArray = map(float, bounds.split(","))
                center = str(postvars['center'][0])
                centerArray = map(float, center.split(","))

                replaceMap = {
                    "timestamp": str(timestamp),
                }

                for key, value in replaceMap.items():
                    newKey = str("{" + str(key) + "}")
                    outputDirectory = outputDirectory.replace(newKey, value)
                    outputFile = outputFile.replace(newKey, value)

                filePath = os.path.join("output", outputDirectory, outputFile)

                self.writerByType(outputType).addMetadata(lock, os.path.join("output", outputDirectory), filePath, outputFile, "Map Tiles Downloader via AliFlux", "png", boundsArray, centerArray, minZoom, maxZoom, "mercator", 256 * outputScale)

                result = {}
                result["code"] = 200
                result["message"] = 'Metadata written'

                self.send_json_response(result)
                return

            elif parts.path == '/end-download':
                outputType = str(postvars['outputType'][0])
                outputScale = int(postvars['outputScale'][0])
                outputDirectory = str(postvars['outputDirectory'][0])
                outputFile = str(postvars['outputFile'][0])
                minZoom = int(postvars['minZoom'][0])
                maxZoom = int(postvars['maxZoom'][0])
                timestamp = int(postvars['timestamp'][0])
                bounds = str(postvars['bounds'][0])
                boundsArray = map(float, bounds.split(","))
                center = str(postvars['center'][0])
                centerArray = map(float, center.split(","))

                replaceMap = {
                    "timestamp": str(timestamp),
                }

                for key, value in replaceMap.items():
                    newKey = str("{" + str(key) + "}")
                    outputDirectory = outputDirectory.replace(newKey, value)
                    outputFile = outputFile.replace(newKey, value)

                filePath = os.path.join("output", outputDirectory, outputFile)

                self.writerByType(outputType).close(lock, os.path.join("output", outputDirectory), filePath, minZoom, maxZoom)

                result = {}
                result["code"] = 200
                result["message"] = 'Downloaded ended'

                self.send_json_response(result)
                return

        except BrokenPipeError:
            logger.warning("Client disconnected during request processing")
            return
        except ConnectionResetError:
            logger.warning("Connection reset by client during request processing")
            return
        except Exception as e:
            logger.error(f"Error in do_POST: {str(e)}", exc_info=True)
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            except:
                logger.error("Failed to send error response", exc_info=True)
                return

    def do_GET(self):
        try:
            parts = urlparse(self.path)
            path = parts.path.strip('/')

            # Handle special case for mapbox token endpoint
            if path == "mapbox-token":
                # Get token from environment variable or use default
                mapbox_token = os.environ.get("MAPBOX_ACCESS_TOKEN", DEFAULT_MAPBOX_TOKEN)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                # Return token as JSON
                token_response = {"token": mapbox_token}
                self.wfile.write(json.dumps(token_response).encode('utf-8'))
                return

            if path == "":
                path = "index.htm"

            file = os.path.join("./UI/", path)
            mime = mimetypes.MimeTypes().guess_type(file)[0]

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.end_headers()

            with open(file, "rb") as f:
                self.wfile.write(f.read())
        except BrokenPipeError:
            logger.warning("Client disconnected unexpectedly")
            return
        except Exception as e:
            logger.error(f"Error in do_GET: {str(e)}", exc_info=True)
            try:
                self.send_response(404)
                self.end_headers()
            except:
                logger.error("Failed to send 404 response", exc_info=True)
                return

class serverThreadedHandler(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    # Set daemon_threads to True so threads exit when main program exits
    daemon_threads = True

    # Add a graceful shutdown method
    def shutdown_gracefully(self):
        logger.info("Shutting down server gracefully...")
        self.shutdown()

def run():
    print('Starting Server...')
    server_address = ('', 8080)
    httpd = serverThreadedHandler(server_address, serverHandler)
    print('Running Server...')

    print("Open http://localhost:8080/ to view the application.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("Keyboard interrupt received, shutting down server...")
        httpd.shutdown_gracefully()
    except Exception as e:
        print(f"Server error: {str(e)}")
        httpd.shutdown_gracefully()

if __name__ == "__main__":
    # Create necessary directories
    os.makedirs("temp", exist_ok=True)
    os.makedirs("output", exist_ok=True)

    run()
