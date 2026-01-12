#!/usr/bin/env python3
"""
Download callback service for marking files as downloaded.

This HTTP service receives callbacks from nginx when a file download completes
and creates marker files to indicate the file can be cleaned up.
"""

import os
import json
import logging
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Marker file suffix
MARKER_SUFFIX = ".downloaded"


def get_download_directory() -> Path:
    """Get the download directory path from environment variable or use default."""
    download_dir = os.getenv("ABHUNTER_DOWNLOAD_DIR", "./downloads")
    download_path = Path(download_dir)
    return download_path


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for download callbacks."""
    
    def do_POST(self):
        """Handle POST requests to mark files as downloaded."""
        if self.path.startswith('/mark-downloaded'):
            try:
                filename = None
                
                # Try to get filename from query parameter first (for nginx proxy)
                parsed_path = urlparse(self.path)
                query_params = parse_qs(parsed_path.query)
                if 'filename' in query_params:
                    filename = query_params['filename'][0]
                
                # If not in query, try to read from request body (JSON)
                if not filename:
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > 0:
                        body = self.rfile.read(content_length)
                        try:
                            data = json.loads(body.decode('utf-8'))
                            filename = data.get('filename')
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.debug(f"Could not parse JSON body: {e}, trying query param")
                
                if not filename:
                    logger.error("Missing filename in request")
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Missing filename'}).encode())
                    return
                
                # Create marker file
                download_dir = get_download_directory()
                file_path = download_dir / filename
                marker_path = download_dir / f"{filename}{MARKER_SUFFIX}"
                
                # Verify the file exists
                if not file_path.exists():
                    logger.warning(f"File does not exist: {filename}")
                    self.send_response(404)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'File not found'}).encode())
                    return
                
                # Create marker file atomically
                try:
                    marker_path.touch()
                    logger.info(f"Marked file as downloaded: {filename}")
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': 'success', 'filename': filename}).encode())
                except OSError as e:
                    logger.error(f"Failed to create marker for {filename}: {e}")
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Failed to create marker'}).encode())
                    
            except Exception as e:
                logger.error(f"Error processing callback: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Internal server error'}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        """Handle GET requests for health checks."""
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'healthy')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.debug(f"{self.address_string()} - {format % args}")


def main():
    """Main entry point for callback service."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Download callback service")
    parser.add_argument(
        '--port',
        type=int,
        default=8888,
        help='Port to listen on (default: 8888)'
    )
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    
    args = parser.parse_args()
    
    download_dir = get_download_directory()
    download_dir.mkdir(parents=True, exist_ok=True)
    
    server_address = (args.host, args.port)
    httpd = HTTPServer(server_address, CallbackHandler)
    
    logger.info(f"Starting download callback service on {args.host}:{args.port}")
    logger.info(f"Download directory: {download_dir}")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Callback service stopped by user")
        httpd.shutdown()


if __name__ == "__main__":
    main()
