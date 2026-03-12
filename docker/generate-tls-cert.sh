#!/bin/bash
# Generate self-signed TLS certificate for HAProxy
# Run once on management host, then distribute to all central nodes.

set -e

CERT_DIR="$(dirname "$0")/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/monctl.key" \
  -out "$CERT_DIR/monctl.crt" \
  -subj "/CN=monctl.local" \
  -addext "subjectAltName=IP:10.145.210.40,IP:10.145.210.41,IP:10.145.210.42,IP:10.145.210.43,IP:10.145.210.44,DNS:monctl.local"

# HAProxy needs key+cert in one PEM file
cat "$CERT_DIR/monctl.key" "$CERT_DIR/monctl.crt" > "$CERT_DIR/monctl.pem"
chmod 600 "$CERT_DIR/monctl.pem" "$CERT_DIR/monctl.key"

echo "TLS certificate generated in $CERT_DIR/"
echo "  monctl.crt  — certificate"
echo "  monctl.key  — private key"
echo "  monctl.pem  — combined (for HAProxy)"
echo ""
echo "Distribute to central nodes:"
echo "  for IP in 10.145.210.{41..44}; do"
echo "    scp -r $CERT_DIR monctl@\$IP:/opt/monctl/central/certs"
echo "  done"
