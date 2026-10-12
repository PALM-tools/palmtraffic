# PALM-traffic

The Python scripts for creation of the PIDS_TRAFFIC input driver for PALM Traffic model (TRM) 
from transportation intensity data (GIS and CSV). They require PostgreSQL server with
a configured database with installed PostGIS database extension. These scripts are not supposed
to be run as they are, but they are provided as templates which can be easily addapted for user
individual input data.


The script traffic_driver.py creates the driver in the format suitable for the PALM Traffic model version 1.0
which is part of the PALM Model System version 25.10. The script utilizes two stored SQL procedures 
ep_create_grid and ep_intersection, which are part of the emission model FUME
(http://www.fume-ep.org, https://github.com/FUME-dev). To install them into your database, 
download files ep_create_grid.sql and ep_intersection.sql from FUME subdirectory "server" 
and run them (e.g. in Query Tool in PgAdmin).


The script traffic_driver_v2.py creates the driver in the format suitable for the PALM Traffic model version 2.0
which is part of the PALM Model System version 26.10. It does not require any additional server SQL procedures.


