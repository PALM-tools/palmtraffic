#!/bin/python3

#------------------------------------------------------------------------------------------------------
# An example python script for creation of the PIDS_TRAFFIC driver for PALM Traffic Module v.2.0 (TRM).
# This script was adjusted from script used for creation of the traffic driver for air quality tests
# in Section 5.3 Impact on the air quality of the paper:
# Resler, J., Belda, M., Bures, M., Eben, K., Fuka, V., Geletic, J., Keder, J., Krc, P., Kvetonová, V.,
# Pikousová, T., Radovic, J., Reznícek, H., Tesarová, P., and Vlcek, O.:
# PALM-Traffic 2.0: Implementation of the traffic-induced heat and velocity in the PALM model system,
# EGUsphere [preprint], https://doi.org/10.5194/egusphere-2026-5699, 2026.
#
# Authors:
# --------
# Jaroslav Resler
#
# Copyright 2024-2026 Institute of Computer Science of the Czech Academy of Sciences, Prague, Czech Republic
#
# License: GNU General Public License version 3.
#
#
# Description:
# ------------
#
# The Python script for creation of the TRM input driver PIDS_TRAFFIC
# from transportation intensity data (GIS and CSV).
# It requires PostgreSQL server with a configured database with
# installed PostGIS database extension.
#
#--------------------------------------------------------------------------------------------------

import os
import sys
from datetime import datetime, timedelta
import pytz
import math
import numpy as np
import getpass
import psycopg2
import csv
from netCDF4 import Dataset

if (len(sys.argv) < 3):
    print('Name of the episode and domain resolution')
    exit(1)

episode = sys.argv[1]
resolution = sys.argv[2]

# List of available episodes with start date and number of hours.
episodes = {'s06':['2023-02-12 18:00:00 +0000',30],
            'pro1':['2022-07-17 18:00:00 +0000',30],
            'pro2':['2022-08-02 18:00:00 +0000',30],
            'pro3':['2023-01-27 18:00:00 +0000',30],
            'pro4':['2023-02-13 18:00:00 +0000',30]}

ep_start = episodes[episode][0]
if (ep_start==""):
    print('Input name of the simulation')
    exit(1)

ep_num_hours = episodes[episode][1]

# Process geometry
process_geometry = True

# Definition of the domains and grids
if resolution == '20':
   grid_nx = 400
   grid_ny = 400
   grid_delx = 20
   grid_dely = 20
   grid_xorg = 455200.
   grid_yorg = 5543000.
elif resolution == '04':
   grid_nx = 300
   grid_ny = 400
   grid_delx = 4
   grid_dely = 4
   grid_xorg = 458600.
   grid_yorg = 5546200.
elif resolution == '01':
#  traffic paper
   grid_nx = 320
   grid_ny = 704
   grid_delx = 1
   grid_dely = 1
   grid_xorg = 459040.
   grid_yorg = 5546648.
elif resolution == '01p':
   #promika
   grid_nx = 288
   grid_ny = 1136
   grid_delx = 1
   grid_dely = 1
   grid_xorg = 459056.
   grid_yorg = 5546464.
else:
   print('Unknown resolution ', resolution)
   exit(1)

# Database info
dbhost='localhost'
dbport='5432'
dbuser='dbuser'  # replace by PostgreSQL user name
dbpasswd = getpass.getpass()
database = 'palm_trans'
basecase = 'trans_legerova'
schema = basecase

# Names of the tables and files
#scen = '_scen'
scen = ''
table_main = 'line_sources_main_promika'+scen
table_aux = 'line_sources_aux_promika'+scen
table_lines = '_lines'
table_traffic = 'traffic_intensity'+'_'+resolution
table_streams = 'traffic_streams'+'_'+resolution
table_out_pk = 's'
table_out_coef = 'frac'
out_filename = 'traffic_'+basecase+scen+'_'+episode+'_'+resolution

# SRID of GIS data and PALM domains
srid_line = 32633
srid_palm = 32633

# Default streets info.
linewidth = 3.5  # (m)
speed = 35       # (km/h)
kmh2ms = 1/3.6   # speed conversion from km/h to m/s
speedstd = 10    # (km/h) standard deviation of speed
gidaux = 1000000 # offset of gid for aux street

# Types of the cars and their default properties.
car_type = ['pc', 'tl', 'th', 'bus']         # personal car, small truck, heavy truck, bus
itpc = 0
ittl = 1
itth = 2
itbus = 3
car_cd = [0.35, 0.35, 0.35, 0.35]            # aerodynamic drag coefficient
car_length = [5.0, 10.0, 18.0, 14.0]         # standard bus 12, articulated bus 18
car_width = [2.0, 2.5, 2.6, 2.55]
car_height = [1.8, 3.5, 4.0, 3.5]
car_consumption = [8.0, 15.0, 35.0, 25.0]    # average car consumption in the city conditions (l/100km)
specific_heat = [31.82, 35.79, 35.79, 35.79] # calculated from prevailing fuel type (MJ/l)
#petrol 43.59*730/1000 = 31.8207 MJ/l
#diesel 42.61*840/1000 = 35.7924

# Tntevals per hour (length of the output time step).
iph = 1

# Name of the csv file with time profiles and its properties.
profile_filename = 'Chody2022_2023.csv'
cet = pytz.timezone('CET')
csv_delimiter = ','
csv_quote = '"'
# Categories of the streets.
cat_default = 3
cat_id_list = [
['A14_201', 'A14_202', 'A14_1276', 'A14_1275', 'A14_1274', 'A14_1277', 'A14_1329', 'A14_1336', 'A14_1337' ],
['A14_199', 'A14_200', 'A14_1285', 'A14_1286', 'A14_196', 'A14_197', 'A14_198', 'A14_1327', 'A14_1334', 'A14_1335'],
[]
]
#cat_id_list = ["0","1","2","3","0_0","0_1","0_2","0_3","1_1","1_2","1_3","2_2","2_3","3_3"]
#cat_column_oa = 'cat_oa'
#cat_column_na = 'cat_na'
cat_column = 'cat'
id_column = 'id'

# Output netcdf file properties.
fillvalue_i = -999
fillvalue_f = -9999.
type_i = 'i4'
type_f = 'f4'
type_s = 'c'
field_length = 23


####################################################
# End of the configuration, start of the processing.
####################################################
# Connect to the database
con = psycopg2.connect(database=database, host=dbhost, port=dbport, user=dbuser, password=dbpasswd)
con.set_client_encoding('UTF8')
cur = con.cursor()

if process_geometry:

    # Check and fix the possible wrong orientation of the line.
    sqltext = "update {s}.{t} set geom = ST_Reverse(geom) where ST_Distance(ST_StartPoint(geom), ST_Transform(ST_SetSRID(ST_MakePoint(x1, y1), {sl}), {sp})) > ST_Distance(ST_StartPoint(geom), ST_Transform(ST_SetSRID(ST_MakePoint(x2, y2), {sl}), {sp}))"\
                .format(sl=srid_line, sp=srid_palm, s=schema, t=table_main)
    cur.execute(sqltext)
    con.commit()

    # Process main and auxiliary streets tables.
    for table in [table_main, table_aux]:
        if table == table_main:
           traffic_sum = 'oa1+nl1+nt1+bus1+oa2+nl2+nt2+bus2'
           traffic_fields = 'orig.oa1, orig.nl1, orig.nt1, orig.bus1, orig.oa2, orig.nl2, orig.nt2, orig.bus2, '
           orig_id = 'orig.id, '
        else:
           traffic_sum = 'oa+nl+nt+bus'
           traffic_fields = 'orig.oa, orig.nl, orig.nt, orig.bus, '
           orig_id = ''

        sqltext = 'alter table "{s}"."{t}" '\
                  ' add column if not exists "smery" INTEGER, '\
                  ' add column if not exists "jpruh" INTEGER'\
                  .format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()

        # Check and fix number of directions.
        sqltext = 'update {s}.{t} set smery = 2 '\
                  ' where (smery is null or smery = 0 )'\
                  .format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()

        # Check and fix number of lines for havy traffic streets.
        sqltext = 'update {s}.{t} set jpruh = 3*smery '\
                  ' where (jpruh is null or jpruh = 0 ) and (' + traffic_sum + ')/smery > 30000 '
        sqltext = sqltext.format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()

        sqltext = 'update {s}.{t} set jpruh = 2*smery '\
                  ' where (jpruh is null or jpruh = 0 ) and (' + traffic_sum + ')/smery > 15000 '
        sqltext = sqltext.format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()

        # Check and fix number of lines for other streets.
        sqltext = 'update {s}.{t} set jpruh = smery '\
                  ' where jpruh is null or jpruh < 2*smery '\
                  .format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()


        # Check and fix slope of the street.
        sqltext = 'update {s}.{t} set sklon = 0 '\
                  ' where sklon is null '\
                  .format(s=schema, t=table)
        cur.execute(sqltext)
        con.commit()

        # Supply time profile category.
        # Check and add cat column if missing.
        sqltext = 'ALTER TABLE "{s}"."{t}" ADD COLUMN IF NOT EXISTS "{cat}" INTEGER'.format(s=schema, t=table, cat=cat_column)
        cur.execute(sqltext)
        con.commit()

        # Supply the default value.
        sqltext = 'UPDATE "{s}"."{t}" SET "{c}" = {v} '.format(s=schema, t=table, c=cat_column, v=cat_default)
        cur.execute(sqltext)
        con.commit()

        # Supply listed categories for the main streets.
        if table == table_main:
           for icat in range(len(cat_id_list)):
              print(icat, cat_id_list[icat])
              sqltext = 'UPDATE "{s}"."{t}" SET "{c}" = {v} WHERE "{p}" in {pv}' \
                 .format(s=schema, t=table_main, c=cat_column, v=icat + 1, p=id_column,
                         pv="('" + "','".join(i for i in cat_id_list[icat]) + "')")
              cur.execute(sqltext)
              con.commit()


        # Split general linestrings into individual straight lines.
        table_new = table+table_lines
        sqltext = 'DROP TABLE IF EXISTS "{}"."{}";'.format(schema, table_new)
        cur.execute(sqltext)
        con.commit()
        sqltext = 'CREATE TABLE "{s}"."{tn}" AS ' +\
                  ' WITH vertex_dump AS (SELECT gid, (dumped).path[1] AS part_idx, (dumped).path[2] AS vertex_idx,' +\
                  ' (dumped).geom AS vertex_geom FROM (SELECT gid, ST_DumpPoints(ST_Multi(geom)) AS dumped ' +\
                  ' FROM "{s}"."{t}" ) sub ), ' +\
                  ' segments AS (SELECT gid, ST_MakeLine(vertex_geom, LEAD(vertex_geom) '+\
                  ' OVER (PARTITION BY gid, part_idx ORDER BY vertex_idx)) AS geom FROM vertex_dump) '+\
                  ' SELECT segments.gid, ' + orig_id + ' segments.geom,  ' + \
                  traffic_fields +\
                  ' orig.smery, orig.jpruh, orig.sklon, orig.cat '+\
                  ' FROM segments JOIN "{s}"."{t}" orig ON orig.gid=segments.gid WHERE segments.geom IS NOT NULL'
        sqltext = sqltext.format(s=schema, tn=table_new, t=table)
        cur.execute(sqltext)
        con.commit()

    # Create new table for processed traffic lines.
    sqltext = 'DROP TABLE IF EXISTS "{}"."{}";'.format(schema, table_traffic)
    cur.execute(sqltext)
    con.commit()

    sqltext = 'CREATE TABLE "{}"."{}" ('\
              ' sid integer, '\
              ' slope double precision,'\
              ' speed double precision,' \
              ' speedstd double precision,' \
              ' oa integer,'\
              ' nl integer,'\
              ' nt integer,'\
              ' bus integer,'\
              ' nlines integer,'\
              ' ndirs integer,'\
              ' dir integer,'\
              ' cat integer,'\
              ' geom geometry(Linestring, {})'\
              ')'.format(schema, table_traffic, srid_palm)
    cur.execute(sqltext)
    con.commit()

    # Calculate individual transportation lines from the street properties.
    # Insert main and auxiliary streets.
    # Create parameterized insert query.
    # Speed, speedstd convert from km/h to m/s.
    for (table, source, offset) in [(table_main+table_lines, 1, 0), (table_aux+table_lines, 2, gidaux)]:
        print(table, offset)
        # Create sql insert for creation of the area shapes for traffic lines.
        if source == 1:
           sqltextf = 'INSERT INTO "{s}"."{t}" ' \
                      '(sid, slope, speed, speedstd, oa, nl, nt, bus, nlines, ndirs, dir, cat, geom) ' \
                      'SELECT ' \
                      ' gid, {dir}*sklon, {speed}*{kmh2ms}, {speedstd}*{kmh2ms}, ' \
                      ' oa{idir}, nl{idir}, nt{idir}, bus{idir}, ' \
                      ' jpruh/smery, smery, {dir}, cat, ' \
                      ' case when {dir} < 0 then ST_Reverse(ST_Transform(geom, {srid_palm})) else ST_Transform(geom, {srid_palm}) end ' \
                      ' FROM "{s}"."{m}" ' \
                      ' WHERE smery={ndirs} and (oa{idir}>0 or nl{idir}>0 or nt{idir}>0 or bus{idir}>0)'
        else:
           sqltextf = 'INSERT INTO "{s}"."{t}" ' \
                      '(sid, slope, speed, speedstd, oa, nl, nt, bus, nlines, ndirs, dir, cat, geom) ' \
                      'SELECT ' \
                      ' gid, {dir}*sklon, {speed}*{kmh2ms}, {speedstd}*{kmh2ms}, ' \
                      ' oa/2, nl/2, nt/2, bus/2, ' \
                      ' jpruh/smery, smery, {dir}, cat, ' \
                      ' case when {dir} < 0 then ST_Reverse(ST_Transform(geom, {srid_palm})) else ST_Transform(geom, {srid_palm}) end ' \
                      ' FROM "{s}"."{m}" ' \
                      ' WHERE smery={ndirs} and (oa>0 or nl>0 or nt>0 or bus>0)'

        # Streets with both directions - we need to create separate left and right line.
        # Right line -  transport in the line direction.
        sqltext = sqltextf.format(s=schema, t=table_traffic, m=table, source=source, srid_palm=srid_palm, \
                                  speed=speed, speedstd=speedstd, kmh2ms=kmh2ms, linewidth=linewidth, gidoffset=offset, \
                                  ndirs=2, dir=1, idir=1, pars='endcap=flat join=round side=right')
        cur.execute(sqltext)
        con.commit()

        # Left line -  transport in the oposite direction to the line direction.
        sqltext = sqltextf.format(s=schema, t=table_traffic, m=table, source=source, srid_palm=srid_palm, \
                                  speed=speed, speedstd=speedstd, kmh2ms=kmh2ms, linewidth=linewidth, gidoffset=offset, \
                                  ndirs=2, dir=-1, idir=2, pars='endcap=flat join=round side=left')
        cur.execute(sqltext)
        con.commit()

        # One direction streets - the direction is already synchronized with line geometry direction.
        # ...1 > 0 - trafic direction oriented in the line geometry direction.
        sqltext = sqltextf.format(s=schema, t=table_traffic, m=table, source=source, srid_palm=srid_palm, \
                                  speed=speed, speedstd=speedstd, kmh2ms=kmh2ms, linewidth=linewidth, gidoffset=offset, \
                                  ndirs=1, dir=1, idir=1, pars='endcap=flat join=round side=both')
        cur.execute(sqltext)
        con.commit()

        # ...2 > 0 - trafic direction oriented in the oposite direction to line geometry direction.
        sqltext = sqltextf.format(s=schema, t=table_traffic, m=table, source=source, srid_palm=srid_palm, \
                                  speed=speed, speedstd=speedstd, kmh2ms=kmh2ms, linewidth=linewidth, gidoffset=offset, \
                                  ndirs=1, dir=-1, idir=2, pars='endcap=flat join=round side=both')
        cur.execute(sqltext)
        con.commit()

    # Limit streets to grid extent.
    # Create grid envelope.
    grid_xmax = grid_xorg + grid_nx * grid_delx
    grid_ymax = grid_yorg + grid_ny * grid_dely
    sqltext = 'select ST_MakeEnvelope({}, {}, {}, {}, {})'.format(grid_xorg, grid_yorg, grid_xmax, grid_ymax, srid_palm)
    cur.execute(sqltext)
    ex = cur.fetchone()
    grid = ex[0]
    con.commit()

    # Delete lines fully outside the grid.
    sqltext = 'delete from "{}"."{}" where not ST_Intersects(geom,%s)'.format(schema, table_traffic)
    cur.execute(sqltext, (grid,))
    con.commit()

    # Convert lines to the transportation streams.
    # Create new table for streams.
    sqltext = 'DROP TABLE IF EXISTS "{}"."{}";'.format(schema, table_streams)
    cur.execute(sqltext)
    con.commit()

    sqltext = 'CREATE TABLE "{}"."{}" ('\
              ' sid integer primary key,'\
              ' startx double precision,'\
              ' starty double precision,'\
              ' endx double precision,'\
              ' endy double precision,'\
              ' slope double precision,'\
              ' speed double precision,'\
              ' speedstd double precision,'\
              ' oa integer,'\
              ' nl integer,'\
              ' nt integer,'\
              ' bus integer,'\
              ' cat integer,'\
              ' geom geometry(Linestring, {})'\
              ')'.format(schema, table_streams, srid_palm)
    cur.execute(sqltext)
    con.commit()

    sqltext = 'SELECT sid, slope, speed, speedstd, oa, nl, nt, bus, nlines, ndirs, ' \
              ' cat, geom FROM "{}"."{}"'.format(schema, table_traffic)
    cur.execute(sqltext)
    rows = cur.fetchall()
    con.commit()

    # Order of the collumnt in the select result.
    jsid, jslope, jspeed, jspeedstd, joa, jnl, jnt, jbus, jnlines, jndirs, jcat, jgeom \
                                                                         = 0,1,2,3,4,5,6,7,8,9,10,11
    # Insert individual lines into the stream table.
    sqltext = 'INSERT INTO "{}"."{}" ' \
              ' (sid, slope, speed, speedstd, oa, nl, nt, bus, cat, geom) ' \
              ' values (%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_OffsetCurve(%s,%s,%s))'\
              .format(schema, table_streams)
    ###
    # Remark: behaviour of the postgis function with geos ver >=3.11, older versions behave differently.
    # Preserve line orientation
    # Shift is relative to the line orientation, positive offset ->left, negative offset -> right
    ###
    cpars = 'join=round'
    sid = 0
    for row in rows:
       nlines = row[jnlines]
       ndirs = row[jndirs]
       print(nlines, ndirs)
       loa = row[joa]/nlines
       lnl = row[jnl]/nlines
       lnt = row[jnt]/nlines
       lbus = row[jbus]/nlines
       if ndirs == 1:
          # One directional street.
          if nlines%2 == 0:
             # Even number of lines.
             for iline in range(int(nlines/2)):
                # Left
                sid += 1
                lineoffset = (0.5+iline)*linewidth
                print(lineoffset)
                cur.execute(sqltext, (sid,row[jslope],row[jspeed],row[jspeedstd],\
                   loa,lnl,lnt,lbus,row[jcat],\
                   row[jgeom],lineoffset,cpars,))
                con.commit()
                # Right
                sid += 1
                lineoffset = -(0.5+iline)*linewidth
                print(lineoffset)
                cur.execute(sqltext, (sid,row[jslope],row[jspeed],row[jspeedstd],\
                   loa,lnl,lnt,lbus,row[jcat],\
                   row[jgeom],lineoffset,cpars,))
                con.commit()
          else:
             # Odd number of lines.
             # Central line.
             sid += 1
             lineoffset = 0
             print(lineoffset)
             cur.execute(sqltext, (sid, row[jslope],row[jspeed],row[jspeedstd],\
                   loa, lnl, lnt, lbus, row[jcat],\
                   row[jgeom], lineoffset, cpars,))
             con.commit()
             # Other lines.
             for iline in range(1,int((nlines + 1) / 2)):
                # Left.
                sid += 1
                lineoffset = iline*linewidth
                print(lineoffset)
                cur.execute(sqltext, (sid, row[jslope],row[jspeed],row[jspeedstd],\
                   loa, lnl, lnt, lbus, row[jcat],\
                   row[jgeom], lineoffset, cpars,))
                con.commit()
                # Right.
                sid += 1
                lineoffset = -iline * linewidth
                print(lineoffset)
                cur.execute(sqltext, (sid, row[jslope],row[jspeed],row[jspeedstd],\
                   loa, lnl, lnt, lbus, row[jcat],\
                   row[jgeom], lineoffset, cpars,))
                con.commit()
       else:
          # Case ndirs = 2, nlines are lines in the current direction from the central line.
          # Shift goes to the right -> negative offset.
          for iline in range(nlines):
             sid += 1
             lineoffset = -(0.5+iline)*linewidth
             print(lineoffset)
             cur.execute(sqltext, (sid, row[jslope],row[jspeed],row[jspeedstd],\
                   loa, lnl, lnt, lbus, row[jcat],\
                   row[jgeom], lineoffset, cpars,))
             con.commit()
    #
    # Calculate startx, starty, endx, endy of the streams.
    sqltext = 'update "{}"."{}" set '\
              ' startx = ST_X(ST_StartPoint(geom)), starty = ST_Y(ST_StartPoint(geom)), '\
              ' endx = ST_X(ST_EndPoint(geom)), endy = ST_Y(ST_EndPoint(geom)) '\
              .format(schema, table_streams)
    cur.execute(sqltext)
    con.commit()

# Write the netcdf file.
# Calculate s dimension.
sqltext = 'SELECT count(*), max(sid) FROM "{s}"."{t}"'.format(s=schema, t=table_streams)
cur.execute(sqltext)
nstreams, sdim_check = cur.fetchone()
con.commit()

if nstreams != sdim_check:
    print('Number of elements does not correspond to s:', nstreams, sdim_check)

# Calculate episode start and end.
dt_start = datetime.strptime(ep_start, '%Y-%m-%d %H:%M:%S %z')
dt_end = dt_start + timedelta(hours=ep_num_hours)

# Read time profiles.
# Time profiles csv properties.
csv_delimiter = ','
csv_quote = '"'
# Read profiles.
nts = 0
tpfile = open(profile_filename, newline='', mode='r')
tpreader = csv.reader(tpfile, delimiter=csv_delimiter, quotechar=csv_quote)
next(tpreader)
rows = []
for row in tpreader:
  dt = datetime.strptime(row[0] + '00', '%d.%m.%Y %H:%M %z')
  dt = dt.astimezone(pytz.utc)
  if dt >= dt_start and  dt <= dt_end:
      rown = []
      rown.append(dt)
      for i in range(3,len(row)):
          rown.append(float(row[i]))
      rows.append(rown)
tpfile.close()
rows.sort()
tslist = []
catlist = []
for row in rows:
  tslist.append(row[0])
  catlist.append([row[2],row[2],row[3]])
catarray = np.array(catlist)
nts = len(tslist)
print('tslist:', tslist)

# Create netcdf file.
filepath = os.path.dirname(os.path.abspath(out_filename))
if not os.path.exists(filepath):
 os.makedirs(filepath)
print('Filename:', out_filename)
ncfile = Dataset(out_filename, 'w', format='NETCDF4')

# Create dimensions (iph - number of output time steps in one hour).
tsdim = ncfile.createDimension('time', (nts-1) * iph + 1)
ncartype = len(car_type)
cdim = ncfile.createDimension('car_type', ncartype)
sdim = ncfile.createDimension('car_stream', nstreams)
fldim = ncfile.createDimension('field_length', field_length)

# Create variables.
# Timestamp.
var_ts = ncfile.createVariable('timestamp', 'c',('time', 'field_length'), fill_value=chr(0))
var_ts._Encoding = 'ascii'
# s - index.
#var_s = ncfile.createVariable('s', type_i, ('s',), fill_value=fillvalue_i)
# Car_type - names of the car types.
var_car_type = ncfile.createVariable('car_type', 'c',('car_type', 'field_length',), fill_value=chr(0))
var_car_type._Encoding = 'ascii'
# Car type parameters.
var_car_cd     = ncfile.createVariable('car_cd', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_length = ncfile.createVariable('car_length', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_width  = ncfile.createVariable('car_width', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_height = ncfile.createVariable('car_height', type_f, ('car_type',), fill_value=fillvalue_f)

# Car stream variables (time invariant).
# Width, slope - widh and slope of the street belt.
var_slope = ncfile.createVariable('stream_slope', type_f, ('car_stream',), fill_value=fillvalue_f)
# Startx, starty, endx, endy - street directional vector.
var_startx = ncfile.createVariable('stream_x1', type_f, ('car_stream',), fill_value=fillvalue_f)
var_starty = ncfile.createVariable('stream_y1', type_f, ('car_stream',), fill_value=fillvalue_f)
var_endx = ncfile.createVariable('stream_x2', type_f, ('car_stream',), fill_value=fillvalue_f)
var_endy = ncfile.createVariable('stream_y2', type_f, ('car_stream',), fill_value=fillvalue_f)
# Time dependent variables.
# pc, tl, th, bus - transport intensity (cars per hour) (personal cars, truck light/heavy, buses).
var_intensity = ncfile.createVariable('stream_intensity', type_f, ('time', 'car_stream', 'car_type'), fill_value=fillvalue_f)
# Car heat production (W/car) (average consumption of the cars is so far constant but in the future could be condition dependent)
var_heat = ncfile.createVariable('stream_heat', type_f, ('time', 'car_stream', 'car_type',), fill_value=fillvalue_f)
# Speed - average speed of the cars (m/s) (so far constant but in the future could be time dependent)
var_speed = ncfile.createVariable('stream_speed', type_f, ('time', 'car_stream', 'car_type',), fill_value=fillvalue_f)
# Speedstd - standard deviation of speed (m/s)
var_std = ncfile.createVariable('stream_std', type_f, ('time', 'car_stream', 'car_type',), fill_value=fillvalue_f)

# Fill car type variables.
for ict in range(ncartype):
    var_car_type[ict]    = car_type[ict]
    var_car_cd[ict]      = car_cd[ict]
    var_car_length[ict]  = car_length[ict]
    var_car_width[ict]   = car_width[ict]
    var_car_height[ict]  = car_height[ict]

# Read stream data.
sqltext = 'SELECT sid, slope, startx, starty, endx, endy, speed, speedstd, cat, oa, nl, nt, bus  '\
          ' FROM "{s}"."{t}" ORDER BY sid '.format(s=schema, t=table_streams)
# Order of the columns in the select output.
isid = 0
islope = 1
istartx = 2
istarty = 3
iendx = 4
iendy = 5
ispeed = 6
istd = 7
icat = 8
ipc = 9
itl = 10
ith = 11
ibus = 12
cur.execute(sqltext)
data = cur.fetchall()
con.commit()
# Fill variable values.
# Time invariant variables.
for row in data:
   # sid indexed from 1, Fortran netcdf read array in PALM is also indexed from 1, Python=c indexed from 0.
   ics = row[isid]-1
   print('Writing stream:', ics)
   var_slope[ics] = row[islope]
   var_startx[ics] = row[istartx]
   var_starty[ics] = row[istarty]
   var_endx[ics] = row[iendx]
   var_endy[ics] = row[iendy]
   for its in range(len(tslist)):
      # print('Writing speed time step:', its)
      # Fill timestamp variable.
      dtf = datetime.strftime(tslist[its], '%Y-%m-%d %H:%M:%S %z')[:-2]
      var_ts[its*iph, :len(dtf)] = dtf
      # Time dependent variables.
      # Speed.
      var_speed[its*iph, ics, :] = row[ispeed]
      # Speed STD.
      var_std[its*iph, ics, :] = row[istd]
      # Intensity - apply time profile coefficient.
      # Convert to car per hour.
      # Personal cars.
      var_intensity[its*iph, ics, itpc] = catarray[its, row[icat]-1] * row[ipc] / 24
      # Light truck.
      var_intensity[its*iph, ics, ittl] = catarray[its, row[icat]-1] * row[itl] / 24
      # Heavy truck.
      var_intensity[its*iph, ics, itth] = catarray[its, row[icat]-1] * row[ith] / 24
      # Bus.
      var_intensity[its*iph, ics, itbus] = catarray[its, row[icat]-1] * row[ibus] / 24
      # Car produced heat in W per car.
      for ict in range(ncartype):
         var_heat[its*iph, ics, ict] = car_consumption[ict] / 100000 * row[ispeed] * specific_heat[ict] * 1000000
         # l/100km * 100km/m * m/s * MJ/l * J/MJ = J/s
         # heat * ncars/h:

# Onterpolate values between hours if iph > 1.
for its in range(len(tslist)-1):
    # Fill additional 10 minutes steps.
    for i in range(1,iph):
        ts = its*iph+i
        c1 = (iph-i)/iph
        c2 = i/iph
        dt = tslist[its] + timedelta(minutes=i*60/iph)
        dtf = datetime.strftime(dt, '%Y-%m-%d %H:%M:%S %z')[:-2]
        var_ts[ts, :len(dtf)] = dtf
        var_speed[ts,:,:] = c1 * var_speed[its*iph,:,:] + c2 * var_speed[(its+1)*iph,:,:]
        var_std[ts,:,:] = c1 * var_std[its*iph,:,:] + c2 * var_std[(its+1)*iph,:,:]
        var_intensity[ts,:,:] = c1 * var_intensity[its*iph,:,:] + c2 * var_intensity[(its+1)*iph,:,:]
        var_heat[ts,:,:] = c1 * var_heat[its*iph,:,:] + c2 * var_heat[(its+1)*iph,:,:]


# Close netcdf file.
ncfile.close()
print('Traffic driver done.')
