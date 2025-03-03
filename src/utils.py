#!/usr/bin/env python

import requests
import uuid
import os
import math
import time
import logging

from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("tile-downloader")


class Utils:

    @staticmethod
    def set_log_level(level):
        """Set the logger level - useful for controlling verbosity"""
        global logger
        logger.setLevel(level)

    @staticmethod
    def randomString():
        return uuid.uuid4().hex.upper()[0:6]

    def getChildTiles(x, y, z):
        childX = x * 2
        childY = y * 2
        childZ = z + 1

        return [
            (childX, childY, childZ),
            (childX + 1, childY, childZ),
            (childX + 1, childY + 1, childZ),
            (childX, childY + 1, childZ),
        ]

    def makeQuadKey(tile_x, tile_y, level):
        quadkey = ""
        for i in range(level):
            bit = level - i
            digit = ord("0")
            mask = 1 << (bit - 1)
            if (tile_x & mask) != 0:
                digit += 1
            if (tile_y & mask) != 0:
                digit += 2
            quadkey += chr(digit)
        return quadkey

    @staticmethod
    def num2deg(xtile, ytile, zoom):
        n = 2.0**zoom
        lon_deg = xtile / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        lat_deg = math.degrees(lat_rad)
        return (lat_deg, lon_deg)

    @staticmethod
    def qualifyURL(url, x, y, z):

        scale22 = 23 - (z * 2)

        replaceMap = {
            "x": str(x),
            "y": str(y),
            "z": str(z),
            "scale:22": str(scale22),
            "quad": Utils.makeQuadKey(x, y, z),
        }

        for key, value in replaceMap.items():
            newKey = str("{" + str(key) + "}")
            url = url.replace(newKey, value)

        return url

    @staticmethod
    def mergeQuadTile(quadTiles):

        width = 0
        height = 0

        for tile in quadTiles:
            if tile is not None:
                width = quadTiles[0].size[0] * 2
                height = quadTiles[1].size[1] * 2
                break

        if width == 0 or height == 0:
            return None

        canvas = Image.new("RGB", (width, height))

        if quadTiles[0] is not None:
            canvas.paste(quadTiles[0], box=(0, 0))

        if quadTiles[1] is not None:
            canvas.paste(quadTiles[1], box=(width - quadTiles[1].size[0], 0))

        if quadTiles[2] is not None:
            canvas.paste(
                quadTiles[2],
                box=(width - quadTiles[2].size[0], height - quadTiles[2].size[1]),
            )

        if quadTiles[3] is not None:
            canvas.paste(quadTiles[3], box=(0, height - quadTiles[3].size[1]))

        return canvas

    @staticmethod
    def downloadFile(
        url, destination, x, y, z, max_retries=3, timeout=30, retry_delay=1, quiet=False
    ):
        """
        Download a file with retry functionality
        """
        url = Utils.qualifyURL(url, x, y, z)
        attempts = 0

        # Ensure the temp directory exists
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for {destination}: {str(e)}")
            return 500

        while attempts < max_retries:
            try:
                if not quiet:
                    logger.info(
                        f"Downloading tile from {url} (attempt {attempts+1}/{max_retries})"
                    )

                # Make request with timeout
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()  # Raise exception for 4XX/5XX responses

                # Verify we got actual content
                if len(response.content) == 0:
                    logger.warning(f"Received empty response for tile at x={x}, y={y}, z={z}")
                    attempts += 1
                    if attempts < max_retries:
                        sleep_time = retry_delay * (2 ** (attempts - 1))
                        time.sleep(sleep_time)
                        continue
                    else:
                        return 204  # No content

                # Save the file
                try:
                    with open(destination, "wb") as f:
                        f.write(response.content)

                    # Verify file was written
                    if not os.path.exists(destination) or os.path.getsize(destination) == 0:
                        logger.warning(f"File not written correctly: {destination}")
                        attempts += 1
                        if attempts < max_retries:
                            sleep_time = retry_delay * (2 ** (attempts - 1))
                            time.sleep(sleep_time)
                            continue
                        else:
                            return 500
                except IOError as e:
                    logger.error(f"Failed to write file {destination}: {str(e)}")
                    attempts += 1
                    if attempts < max_retries:
                        sleep_time = retry_delay * (2 ** (attempts - 1))
                        time.sleep(sleep_time)
                        continue
                    else:
                        return 500

                return response.status_code

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout while downloading tile at x={x}, y={y}, z={z}")

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    # Tile doesn't exist, don't retry
                    logger.warning(f"Tile not found (404): x={x}, y={y}, z={z}")
                    if attempts >= max_retries:
                        return 404  # Return 404 after all retries fail
                logger.warning(
                    f"HTTP error {e.response.status_code} for tile at x={x}, y={y}, z={z}"
                )

            except requests.exceptions.RequestException as e:
                logger.warning(f"Error downloading tile: {str(e)}")

            except Exception as e:
                logger.error(f"Unexpected error while downloading tile: {str(e)}")

            # Increment attempts and apply exponential backoff
            attempts += 1
            if attempts < max_retries:
                sleep_time = retry_delay * (2 ** (attempts - 1))  # Exponential backoff
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)

        logger.error(
            f"Failed to download tile after {max_retries} attempts: x={x}, y={y}, z={z}"
        )
        return 500  # Return error code after all retries fail

    @staticmethod
    def downloadFileScaled(
        url,
        destination,
        x,
        y,
        z,
        outputScale=1,
        max_retries=3,
        timeout=30,
        retry_delay=1,
    ):
        """
        Download a file with specific scale and retry functionality
        """
        # Ensure the destination directory exists
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for {destination}: {str(e)}")
            return 500

        if outputScale == 1:
            # Use the retry logic for scale 1
            return Utils.downloadFile(
                url, destination, x, y, z, max_retries, timeout, retry_delay
            )

        elif outputScale == 2:
            # For scale 2, we need to download 4 child tiles with retry logic
            childTiles = Utils.getChildTiles(x, y, z)
            childImages = []
            temp_files = []

            for childX, childY, childZ in childTiles:
                tempFile = Utils.randomString() + ".png"
                tempFilePath = os.path.join("temp", tempFile)
                temp_files.append(tempFilePath)

                # Make sure temp directory exists
                os.makedirs(os.path.dirname(tempFilePath), exist_ok=True)

                # Use downloadFile with retry logic for each child tile
                code = Utils.downloadFile(
                    url,
                    tempFilePath,
                    childX,
                    childY,
                    childZ,
                    max_retries,
                    timeout,
                    retry_delay,
                )

                if code == 200 and os.path.exists(tempFilePath) and os.path.getsize(tempFilePath) > 0:
                    try:
                        image = Image.open(tempFilePath)
                        childImages.append(image)
                    except Exception as e:
                        logger.error(f"Error opening image {tempFilePath}: {str(e)}")
                        childImages.append(None)  # Add None placeholder for missing tile
                else:
                    childImages.append(None)  # Add None placeholder for missing tile

            # Clean up temp files
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except OSError:
                    pass  # Ignore errors removing temp files

            # Try to create a merged tile even if some tiles are missing
            if any(childImages):  # At least one valid image
                try:
                    canvas = Utils.mergeQuadTile(childImages)
                    if canvas:
                        canvas.save(destination, "PNG")
                        return 200
                    else:
                        logger.error("Failed to merge quad tiles")
                        return 500
                except Exception as e:
                    logger.error(f"Error merging or saving quad tile: {str(e)}")
                    return 500
            else:
                logger.error("All child tiles failed to download")
                return 500

        else:
            # For other scales (not supported)
            logger.error(f"Unsupported output scale: {outputScale}")
            return 400  # Bad request

    @staticmethod
    def scaleImage(filePath, scale):
        """Scale an image by the given factor"""
        try:
            with Image.open(filePath) as img:
                width, height = img.size
                new_size = (width * scale, height * scale)
                resized_img = img.resize(new_size, Image.LANCZOS)
                resized_img.save(filePath)
        except Exception as e:
            logger.error(f"Error scaling image {filePath}: {str(e)}")

    @staticmethod
    def tileXYToQuadKey(x, y, z):
        """Convert tile coordinates to a quadkey for Bing Maps"""
        quadKey = ""
        for i in range(z, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if (x & mask) != 0:
                digit += 1
            if (y & mask) != 0:
                digit += 2
            quadKey += str(digit)
        return quadKey
