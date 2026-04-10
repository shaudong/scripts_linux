#!/bin/bash

sudo update-grub
sudo systemctl daemon-reload
sudo update-ca-certificates
sudo systemctl restart docker
