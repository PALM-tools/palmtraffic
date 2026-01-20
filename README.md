# PALM-traffic

The Python script for creation of the PIDS_TRAFFIC input driver for PALM Traffic module (TRM) 
from transportation intensity data (GIS and CSV).
It requires PostgreSQL server with a configured database with installed PostGIS database extension. 
The script utilizes two stored SQL procedures ep_create_grid and ep_intersection, which are part of the
emission model FUME (http://www.fume-ep.org, https://github.com/FUME-dev).
To install them into your database, download files ep_create_grid.sql and ep_intersection.sql 
from FUME subdirectory "server" and run them (e.g. in Query Tool in PgAdmin).

This script is not supposed to be run as it is but it is provided as a template which can be easily addapted
for user individual input data.
