#!/bin/bash
set -e
cd /home/site/wwwroot
python -m app.scripts.sync_all_m365_customers

