#!/bin/python3

#--------------------------------------------------------------------------------------------------
# An example python script for creation of the PIDS_TRAFFIC input driver PALM Traffic Module (TRM).
#
# Authors:
# --------
# Jaroslav Resler
#
# Copyright 2024-2025 Institute of Computer Science of the Czech Academy of Sciences, Prague, Czech Republic
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
# installed PostGIS database extension. The script utilizes two stored SQL
# procedures ep_create_grid and ep_intersection, which are part of the
# emission model FUME (http://www.fume-ep.org, https://github.com/FUME-dev).
# To install them into your database, download files ep_create_grid.sql and
# ep_intersection.sql from FUME subdirectory "server" and run them 
# (e.g. Query Tool in PgAdmin).
#--------------------------------------------------------------------------------------------------

import os
from datetime import datetime
import math
import numpy as np
import getpass
import psycopg2
import csv
from netCDF4 import Dataset

# database info
dbhost='localhost'
dbport='5432'
dbuser='mydbuser'
database = 'palm_traffic'
schema = 'traffic_test'
table_main = 'line_sources_main'
table_aux = 'line_sources_aux'
table_traffic = 'traffic_intensity'
table_out_pk = 's'
table_out_coef = 'frac'
out_path = 'traffic_test'

dbpasswd = getpass.getpass()

# SRID of GIS data and PALM domains
srid_line = 5514
srid_palm = 32633

# streets info
linewidth = 3.5  # (m)
speed = 35       # (km/h)
gidaux = 100000  # offset of gid for aux street

# grid info

# parent domain
resolution = '10'
grid_nx = 800
grid_ny = 800
grid_delx = 10
grid_dely = 10
grid_xorg = 455180.
grid_yorg = 5543800.

# case dependent names
grid_name = 'palm_grid_'+resolution
table_out = 'traffic_intensity_grid_'+resolution
out_filename = out_path+'_'+resolution

# time profiles
profile_filename = 'time_profiles.csv'
csv_delimiter = ','
csv_quote = '"'
cat_default = 3
cat_id_list = [
['A14_201', 'A14_202', 'A14_1276', 'A14_1275', 'A14_1274', 'A14_1277', 'A14_1329', 'A14_1336', 'A14_1337' ],
['A14_199', 'A14_200', 'A14_1285', 'A14_1286', 'A14_196', 'A14_197', 'A14_198', 'A14_1327', 'A14_1334', 'A14_1335'],
[]
]
cat_column = 'cat'
id_column = 'id'

# output netcdf
fillvalue_i = -999
fillvalue_f = -9999.
type_i = 'i4'
type_f = 'f4'
type_s = 'c'
field_length = 23
car_type = ['pc', 'tl', 'th', 'bus']         # personal car, small truck, heavy truck, bus
car_cd = [0.35, 0.35, 0.35, 0.35]            # aerodynamic drag coefficient
car_length = [5.0, 10.0, 18.0, 14.0]         # standard bus 12, articulated bus 18
car_width = [2.0, 2.5, 2.6, 2.55]
car_height = [1.8, 3.5, 4.0, 3.5]
car_consumption = [8.0, 15.0, 35.0, 25.0]    # average car consumption in the city conditions
specific_heat = [31.82, 35.79, 35.79, 35.79] # calculated from prevailing fuel type
#petrol 43.59*730/1000 = 31.8207 MJ/l
#diesel 42.61*840/1000 = 35.7924


##############################
# connect to database
con = psycopg2.connect(database=database, host=dbhost, port=dbport, user=dbuser, password=dbpasswd)
con.set_client_encoding('UTF8')
cur = con.cursor()

# check and fix the possible wrong orientation of the line
sqltext = "update {s}.{t} set geom = ST_Reverse(geom) where ST_Distance(ST_StartPoint(geom), ST_Transform(ST_SetSRID(ST_MakePoint(x1, y1), {sl}), {sp})) > ST_Distance(ST_StartPoint(geom), ST_Transform(ST_SetSRID(ST_MakePoint(x2, y2), {sl}), {sp}))"\
            .format(sl=srid_line, sp=srid_palm, s=schema, t=table_main)
cur.execute(sqltext)
con.commit()

# check and fix number of directions
sqltext = 'update {s}.{t} set smery = 2 '\
          ' where (smery is null or smery <> 2) and '\
          '      (oa1 > 0 or nl1 > 0 or nt1 > 0 or bus1 > 0) and '\
          '      (oa2 > 0 or nl2 > 0 or nt2 > 0 or bus2 > 0) '\
          .format(s=schema, t=table_main)
cur.execute(sqltext)
con.commit()

sqltext = 'update {s}.{t} set smery = 1 '\
          ' where (smery is null or smery < 1) and '\
          '      (oa1 > 0 or nl1 > 0 or nt1 > 0 or bus1 > 0 or '\
          '       oa2 > 0 or nl2 > 0 or nt2 > 0 or bus2 > 0) '\
          .format(s=schema, t=table_main)
cur.execute(sqltext)
con.commit()

# check and fix number of lines
sqltext = 'update {s}.{t} set jpruh = 2 '\
          ' where smery = 2 and jpruh < 2 '\
          .format(s=schema, t=table_main)
cur.execute(sqltext)
con.commit()

sqltext = 'update {s}.{t} set jpruh = 1 '\
          ' where smery = 1 and jpruh < 1 '\
          .format(s=schema, t=table_main)
cur.execute(sqltext)
con.commit()

# supply time profile category
# check and add cat column
sqltext = 'ALTER TABLE "{s}"."{t}" ADD COLUMN IF NOT EXISTS "{c}" INTEGER '.format(s=schema, t=table_main, c=cat_column)
cur.execute(sqltext)
con.commit()

# supply default value
sqltext = 'UPDATE "{s}"."{t}" SET "{c}" = {v} '.format(s=schema, t=table_main, c=cat_column, v=cat_default)
cur.execute(sqltext)
con.commit()

# supply listed categories
for icat in range(len(cat_id_list)):
    print(icat, cat_id_list[icat])
    sqltext = 'UPDATE "{s}"."{t}" SET "{c}" = {v} WHERE "{p}" in {pv}'\
              .format(s=schema, t=table_main, c=cat_column, v=icat+1, p=id_column, pv="('" + "','".join(i for i in cat_id_list[icat]) + "')")
    cur.execute(sqltext)
    con.commit()


# create new table
sqltext = 'DROP TABLE IF EXISTS "{}"."{}";'.format(schema, table_traffic)
cur.execute(sqltext)
con.commit()

sqltext = 'CREATE TABLE "{}"."{}" ('\
          ' gid integer primary key,'\
          ' pid character varying,'\
          ' source integer,'\
          ' length double precision,'\
          ' width double precision,'\
          ' slope double precision,'\
          ' speed double precision,'\
          ' dirx double precision,'\
          ' diry double precision,'\
          ' oa integer,'\
          ' nl integer,'\
          ' nt integer,'\
          ' bus integer,'\
          ' iad integer,'\
          ' udi1 integer,'\
          ' udi2 integer,'\
          ' nlines integer,'\
          ' ndirs integer,'\
          ' dir integer,'\
          ' cat integer,'\
          ' geom geometry(Polygon, {})'\
          ')'.format(schema, table_traffic, srid_palm)
cur.execute(sqltext)
con.commit()

# insert main streets

# calculate shape and parameters of the buffer lines
# update query - parameterized
sqltextf = 'INSERT INTO "{s}"."{t}" ' \
           '(gid, pid, source, length, width, slope, speed, dirx, diry, ' \
           'oa, nl, nt, bus, iad, udi1, udi2, nlines, ndirs, dir, cat, geom) '\
           'SELECT ' \
           ' {dir}*gid, id, 1, ST_Length(geom), jpruh*{linewidth}/smery, {dir}*sklon, {speed}, ' \
           ' {dir}*(ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom)))/SQRT(POWER((ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom))),2) + POWER((ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom))),2)), ' \
           ' {dir}*(ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom)))/SQRT(POWER((ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom))),2) + POWER((ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom))),2)), ' \
           ' oa{idir}, nl{idir}, nt{idir}, bus{idir}, ' \
           ' iad, udi1, udi2, jpruh/smery, smery, {dir}, cat, ' \
           ' ST_Buffer(geom, jpruh*{linewidth}/2, \'{pars}\') '\
           'FROM "{s}"."{m}" '\
           'WHERE smery={ndirs} and (oa{idir}>0 or nl{idir}>0 or nt{idir}>0 or bus{idir}>0)'

# both directions - we need to create separate left and right line
# right line -  transport in line direction
sqltext = sqltextf.format(s=schema, t=table_traffic, m=table_main, speed=speed, linewidth=linewidth, ndirs=2, dir=1, idir=1, pars='endcap=flat join=round side=right')
cur.execute(sqltext)
con.commit()
# left line -  transport in oposite direction to line direction
sqltext = sqltextf.format(s=schema, t=table_traffic, m=table_main, speed=speed, linewidth=linewidth, ndirs=2, dir=-1, idir=2, pars='endcap=flat join=round side=left')
cur.execute(sqltext)
con.commit()
# one direction - the direction is already synchronized with line geometry direction
# ...1 > 0 - trafic direction oriented in the line geometry direction
sqltext = sqltextf.format(s=schema, t=table_traffic, m=table_main, speed=speed, linewidth=linewidth, ndirs=1, dir=1, idir=1, pars='endcap=flat join=round side=both')
cur.execute(sqltext)
con.commit()
# ...2 > 0 - trafic direction oriented in the oposite direction to line geometry direction
sqltext = sqltextf.format(s=schema, t=table_traffic, m=table_main, speed=speed, linewidth=linewidth, ndirs=1, dir=-1, idir=2, pars='endcap=flat join=round side=both')
cur.execute(sqltext)
con.commit()

# process and insert auxiliary streets
sqltextf = 'INSERT INTO "{s}"."{t}" ' \
           '(gid, pid, source, length, width, slope, speed, dirx, diry, ' \
           'oa, nl, nt, bus, nlines, ndirs, dir, cat, geom) '\
           'SELECT ' \
           ' {dir}*gid+{gidaux}, \'\', 2, ST_Length(geom), {linewidth}, {dir}*sklon, rychlost, ' \
           ' {dir}*(ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom)))/SQRT(POWER((ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom))),2) + POWER((ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom))),2)), ' \
           ' {dir}*(ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom)))/SQRT(POWER((ST_X(ST_EndPoint(geom))-ST_X(ST_StartPoint(geom))),2) + POWER((ST_Y(ST_EndPoint(geom))-ST_Y(ST_StartPoint(geom))),2)), ' \
           ' oa/2, nl/2, nt/2, bus/2, ' \
           ' 1, 2, {dir}, {cat}, ' \
           ' ST_Buffer(geom, {linewidth}, \'{pars}\') '\
           'FROM "{s}"."{a}" '\
           'WHERE oa>0 or nl>0 or nt>0 or bus>0'

# right line -  transport in line direction
sqltext = sqltextf.format(s=schema, t=table_traffic, a=table_aux, gidaux=gidaux, speed=speed, linewidth=linewidth, ndirs=2, dir=1, cat=cat_default, pars='endcap=flat join=round side=right')
cur.execute(sqltext)
con.commit()

# left line -  transport in oposite direction to line direction
sqltext = sqltextf.format(s=schema, t=table_traffic, a=table_aux, gidaux=gidaux, speed=speed, linewidth=linewidth, ndirs=2, dir=-1, cat=cat_default, pars='endcap=flat join=round side=left')
cur.execute(sqltext)
con.commit()

# ########
# convert to grid

# first create grid
# ep_create_grid needs centre of the grid
grid_xcent = grid_xorg + grid_nx*grid_delx/2
grid_ycent = grid_yorg + grid_ny*grid_dely/2

# call FUME create grid procedure
cur.callproc('ep_create_grid', [schema, grid_name, grid_nx, grid_ny, grid_delx, grid_dely, grid_xcent, grid_ycent, srid_palm])
con.commit()

# call FUME intersection procedure
fields1 = ['gid', 'pid', 'source', 'length', 'width', 'slope', 'speed', 'dirx', 'diry', 'oa', 'nl', 'nt', 'bus', 'iad', 'udi1', 'udi2', 'nlines', 'ndirs', 'dir', 'cat']
fields2 = ['grid_id', 'i', 'j']
scale = True
normalize = False
createtable = True
temptable = False

q = cur.mogrify('SELECT * FROM ep_intersection('
            '%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s )', [
           schema, grid_name, '{'+','.join(i for i in fields2)+'}', '',
           schema, table_traffic, '{'+','.join([i for i in fields1])+'}', '',
           schema, table_out, srid_palm, table_out_pk, 'geom', table_out_coef,
           scale, normalize, createtable, temptable])
res = cur.execute(q)
con.commit()
print('Intersect result:', res)

# normalize coeficient from grid size
sqltext = 'UPDATE "{s}"."{t}" set {coef} = {coef}/{dx}/{dy}'.format(s=schema, t=table_out, coef=table_out_coef, dx=grid_delx, dy=grid_dely)
cur.execute(sqltext)
con.commit()

# calculate dimension of the s
sqltext = 'SELECT count(*), max(s) FROM "{s}"."{t}"'.format(s=schema, t=table_out)
cur.execute(sqltext)
ns, sdim_check = cur.fetchone()
con.commit()

if ns != sdim_check:
    print('Number of elements does not correspond to s:', ns, sdim_check)

# read time profiles
tpfile = open(profile_filename, newline='', mode='r')
tpreader = csv.reader(tpfile, delimiter=csv_delimiter, quotechar=csv_quote)
next(tpreader)
rows = []
for row in tpreader:
    dt = datetime.strptime(row[0] + '00', '%d.%m.%Y %H:%M %z')
    rows.append([datetime.strftime(dt, '%Y-%m-%d %H:%M:%S %z')[:-2], float(row[3]), float(row[4]), float(row[5])])
tpfile.close()
rows.sort()
tslist = []
catlist = []
for row in rows:
    tslist.append(row[0])
    catlist.append([row[1],row[2],row[3]])
catarray = np.array(catlist)
nts = len(tslist)

# save to netcdf file
filepath = os.path.dirname(os.path.abspath(out_filename))
if not os.path.exists(filepath):
    os.makedirs(filepath)

# create netcdf file
print('Filename:', out_filename)
ncfile = Dataset(out_filename, 'w', format='NETCDF4')

# create dimensions
tsdim = ncfile.createDimension('time', nts)
sdim = ncfile.createDimension('s', ns)
ncartype = len(car_type)
cdim = ncfile.createDimension('car_type', ncartype)
fldim = ncfile.createDimension('field_length', field_length)

# create variables
# timestamp
var_ts = ncfile.createVariable('timestamp', 'c',('time', 'field_length'), fill_value=chr(0))
var_ts._Encoding = 'ascii'
# s - index
#var_s = ncfile.createVariable('s', type_i, ('s',), fill_value=fillvalue_i)
# car_type - names of the car types
var_car_type = ncfile.createVariable('car_type', 'c',('car_type', 'field_length',), fill_value=chr(0))
var_car_type._Encoding = 'ascii'
# car type parameters
var_car_cd     = ncfile.createVariable('car_cd', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_length = ncfile.createVariable('car_length', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_width  = ncfile.createVariable('car_width', type_f, ('car_type',), fill_value=fillvalue_f)
var_car_height = ncfile.createVariable('car_height', type_f, ('car_type',), fill_value=fillvalue_f)

## one dim variables (time invariant)
# i,j,k - coordinates
var_i = ncfile.createVariable('i', type_i, ('s',), fill_value=fillvalue_i)
var_j = ncfile.createVariable('j', type_i, ('s',), fill_value=fillvalue_i)
var_k = ncfile.createVariable('k', type_i, ('s',), fill_value=fillvalue_i)
# width, slope - widh and slope of the street belt
var_width = ncfile.createVariable('width', type_f, ('s',), fill_value=fillvalue_f)
var_slope = ncfile.createVariable('slope', type_f, ('s',), fill_value=fillvalue_f)
# dirx, diry - street directional vector
var_dirx = ncfile.createVariable('dirx', type_f, ('s',), fill_value=fillvalue_f)
var_diry = ncfile.createVariable('diry', type_f, ('s',), fill_value=fillvalue_f)
# nlines - number of lines in the street belt
var_nlines = ncfile.createVariable('nlines', type_i, ('s',), fill_value=fillvalue_i)
# frac - percentage of the grid in the street belt
var_frac = ncfile.createVariable('frac', type_f, ('s',), fill_value=fillvalue_f)
## time dependent variables
# pc, tl, th, bus - transport intensity (personal cars, truck light/heavy, buses) (cars per day)
var_intensity = ncfile.createVariable('intensity', type_f, ('time', 's', 'car_type'), fill_value=fillvalue_f)
# car heat production (average consumption of the cars is so far constant but in the future could be condition dependent)
var_heat = ncfile.createVariable('heat', type_f, ('time', 's', 'car_type',), fill_value=fillvalue_f)
# speed - average speed of the cars (so far constant but in the future could be time dependent)
var_speed = ncfile.createVariable('speed', type_f, ('time', 's', 'car_type',), fill_value=fillvalue_f)

# fill timestamp variable
for its in range(len(tslist)):
    var_ts[its, :len(tslist[its])] = tslist[its]

# fill car type variable
for ict in range(ncartype):
    var_car_type[ict]    = car_type[ict]
    var_car_cd[ict]      = car_cd[ict]
    var_car_length[ict]  = car_length[ict]
    var_car_width[ict]   = car_width[ict]
    var_car_height[ict]  = car_height[ict]

# read data
sqltext = 'SELECT i, j, 1, width, slope, dirx, diry, nlines, cat, frac, oa, nl, nt, bus, speed '\
          ' FROM "{s}"."{t}" ORDER BY i, j '.format(s=schema, t=table_out)
cur.execute(sqltext)
data = cur.fetchall()
con.commit()
# convert data to np array
data_array = np.array(data, dtype=\
    [('i', type_i), ('j', type_i), ('k', type_i), ('width', type_f), ('slope', type_f), \
     ('dirx', type_f), ('diry', type_f), ('nlines', type_i), ('cat', type_i), ('frac', type_f), \
     ('pc', type_f), ('tl', type_f), ('th', type_f), ('bus', type_f), ('speed', type_f)])
# fill variable values
# time invariant variables
#var_s[:] = data_array['s'] - 1 # netcdf is indexed from 0
var_i[:] = data_array['i']
var_j[:] = data_array['j']
var_k[:] = data_array['k']
var_width[:] = data_array['width']
var_slope[:] = data_array['slope']
var_dirx[:] = data_array['dirx']
var_diry[:] = data_array['diry']
var_nlines[:] = data_array['nlines']
var_frac[:] = data_array['frac']
# time dependent variables
# calculate array of coefficients with dimension (ts, s) and value the time profile coefficient
tscoef = catarray[:,data_array['cat']-1] / 24  # convert to car per hour
# time dependent variables - apply time profile coefficient
# speed
tmparray = np.ones(var_speed.shape)
var_speed[:,:,:] = data_array['speed'][np.newaxis,:,np.newaxis]*tmparray/3.6  # convert from km/h to m/s
# intensity
var_intensity[:,:,0] = data_array['pc'][np.newaxis,:] * tscoef[:,:]
var_intensity[:,:,1] = data_array['tl'][np.newaxis,:] * tscoef[:,:]
var_intensity[:,:,2] = data_array['th'][np.newaxis,:] * tscoef[:,:]
var_intensity[:,:,3] = data_array['bus'][np.newaxis,:] * tscoef[:,:]
# car produced heat in W per car
for ict in range(ncartype):
    var_heat[:,:,ict] = car_consumption[ict]/100000 * var_speed[:,:,ict] * specific_heat[ict] * 1000000


# close netcdf file
ncfile.close()
