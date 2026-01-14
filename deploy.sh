#!/bin/bash
# ClearDrive Backend Deployment Script
# Run this on your Linux server after copying the files

set -e

echo "=== ClearDrive Backend Setup ==="

# Check Python version
python3 --version || { echo "Python 3 not found. Install with: sudo apt install python3 python3-pip python3-venv"; exit 1; }

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create systemd service file
echo "Creating systemd service..."
sudo tee /etc/systemd/system/cleardrive.service > /dev/null << 'EOF'
[Unit]
Description=ClearDrive Backend API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/cleardrive
Environment="PATH=/home/$USER/cleardrive/venv/bin"
ExecStart=/home/$USER/cleardrive/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Fix the user in the service file
sudo sed -i "s/\$USER/$USER/g" /etc/systemd/system/cleardrive.service

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable cleardrive
sudo systemctl start cleardrive

# Open firewall port (if ufw is installed)
if command -v ufw &> /dev/null; then
    echo "Opening port 8000 in firewall..."
    sudo ufw allow 8000/tcp
fi

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Server running at: http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status cleardrive   # Check status"
echo "  sudo systemctl restart cleardrive  # Restart server"
echo "  sudo journalctl -u cleardrive -f   # View logs"
echo ""
echo "Update your iOS app's server URL to: http://YOUR_PUBLIC_IP:8000"
