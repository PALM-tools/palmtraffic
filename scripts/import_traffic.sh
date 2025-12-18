#!/bin/bash

# export PGUSER=mydbuser
# export PGPASSWORD=mydatabasepassword

ogr2ogr \
  -nln "traffic_test"."line_sources_main" \
  -lco GEOMETRY_NAME=geom \
  -lco FID=gid \
  -lco PRECISION=NO \
  Pg:"dbname=palm_traffic host=localhost port=5432" \
  line_sources_main.shp


ogr2ogr \
  -nln "traffic_test"."line_sources_aux" \
  -lco GEOMETRY_NAME=geom \
  -lco FID=gid \
  -lco PRECISION=NO \
  Pg:"dbname=palm_traffic host=localhost port=5432" \
  line_sources_aux.shp
