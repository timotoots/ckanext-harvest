from ckan.model import Session
from ckan.model import repo
from ckan.lib.base import config

from ckanext.harvest.model import HarvestSource, HarvestJob


log = __import__("logging").getLogger(__name__)

def get_harvest_source(id,default=Exception,attr=None):
    return HarvestSource.get(id,default=default,attr=attr)

def get_harvest_sources(**kwds):
    return HarvestSource.filter(**kwds).all()

def create_harvest_source(source_dict):
    if not 'url' in source_dict or not source_dict['url'] or \
        not 'type' in source_dict or not source_dict['type']:
        raise Exception('Missing mandatory properties: url, type')

    # Check if source already exists
    exists = get_harvest_sources(url=source_dict['url'])
    if len(exists):
        raise Exception('There is already a Harvest Source for this URL: %s' % source_dict['url'])
    
    source = HarvestSource()
    source.url = source_dict['url']
    source.type = source_dict['type']
    print str(source_dict['active'])
    opt = ['active','description','user_id','publisher_id']
    for o in opt:
        if o in source_dict and source_dict[o] is not None:
            source.__setattr__(o,source_dict[o])

    source.save()

    return source 

def delete_harvest_source(source_id):
    try:
        source = HarvestSource.get(source_id)
    except:
        raise Exception('Source %s does not exist' % source_id)

    source.delete()
    repo.commit_and_remove()
    
    #TODO: Jobs?

    return True

def get_harvest_job(id,attr=None):
    return HarvestJob.get(id,attr)

def get_harvest_jobs(**kwds):
    return HarvestJob.filter(**kwds).all()

def create_harvest_job(source_id):
    # Check if source exists
    try:
        source = get_harvest_source(source_id)
    except:
        raise Exception('Source %s does not exist' % source_id)

    # Check if there already is an unrun job for this source
    exists = get_harvest_jobs(source=source,status=u'New')
    if len(exists):
        raise Exception('There already is an unrun job for this source')

    job = HarvestJob()
    job.source = source
    
    job.save()

    return job

def delete_harvest_job(job_id):
    try:
        job = HarvestJob.get(job_id)
    except:
        raise Exception('Job %s does not exist' % job_id)

    job.delete()
    repo.commit_and_remove()
    
    #TODO: objects?

    return True

#TODO: move to ckanext-?? for geo stuff
def get_srid(crs):
    """Returns the SRID for the provided CRS definition
        The CRS can be defined in the following formats
        - urn:ogc:def:crs:EPSG::4258
        - EPSG:4258
        - 4258
       """

    if ':' in crs:
        crs = crs.split(':')
        srid = crs[len(crs)-1]
    else:
       srid = crs

    return int(srid)

#TODO: move to ckanext-?? for geo stuff    
def save_extent(package,extent=False):
    '''Updates the package extent in the package_extent geometry column
       If no extent provided (as a dict with minx,miny,maxx,maxy and srid keys),
       the values stored in the package extras are used'''

    db_srid = int(config.get('ckan.harvesting.srid', '4258'))
    conn = Session.connection()

    srid = None
    if extent:
        minx = extent['minx'] 
        miny = extent['miny']
        maxx = extent['maxx']
        maxy = extent['maxy']
        if 'srid' in extent:
            srid = extent['srid'] 
    else:
        minx = float(package.extras.get('bbox-east-long'))
        miny = float(package.extras.get('bbox-south-lat'))
        maxx = float(package.extras.get('bbox-west-long'))
        maxy = float(package.extras.get('bbox-north-lat'))
        crs = package.extras.get('spatial-reference-system')
        if crs:
            srid = get_srid(crs) 
    try:
        
        # Check if extent already exists
        rows = conn.execute('SELECT package_id FROM package_extent WHERE package_id = %s',package.id).fetchall()
        update =(len(rows) > 0)
        
        params = {'id':package.id, 'minx':minx,'miny':miny,'maxx':maxx,'maxy':maxy, 'db_srid': db_srid}
        
        if update:
            # Update
            if srid and srid != db_srid:
                # We need to reproject the input geometry
                statement = """UPDATE package_extent SET 
                                the_geom = ST_Transform(
                                            ST_GeomFromText('POLYGON ((%(minx)s %(miny)s, 
                                                            %(maxx)s %(miny)s,
                                                            %(maxx)s %(maxy)s,
                                                            %(minx)s %(maxy)s,
                                                            %(minx)s %(miny)s))',%(srid)s),
                                            %(db_srid)s)
                                WHERE package_id = %(id)s
                                """
                params.update({'srid': srid})
            else:
                statement = """UPDATE package_extent SET 
                                the_geom = ST_GeomFromText('POLYGON ((%(minx)s %(miny)s, 
                                                            %(maxx)s %(miny)s,
                                                            %(maxx)s %(maxy)s,
                                                            %(minx)s %(maxy)s,
                                                            %(minx)s %(miny)s))',%(db_srid)s)
                                WHERE package_id = %(id)s
                                """
            msg = 'Updated extent for package %s' 
        else:
            # Insert
            if srid and srid != db_srid:
                # We need to reproject the input geometry
                statement = """INSERT INTO package_extent (package_id,the_geom) VALUES (
                                %(id)s,
                                ST_Transform(
                                    ST_GeomFromText('POLYGON ((%(minx)s %(miny)s, 
                                                            %(maxx)s %(miny)s,
                                                            %(maxx)s %(maxy)s,
                                                            %(minx)s %(maxy)s,
                                                            %(minx)s %(miny)s))',%(srid)s),
                                        %(db_srid))
                                        )"""
                params.update({'srid': srid})          
            else:
                statement = """INSERT INTO package_extent (package_id,the_geom) VALUES (
                                %(id)s,
                                ST_GeomFromText('POLYGON ((%(minx)s %(miny)s, 
                                                            %(maxx)s %(miny)s,
                                                            %(maxx)s %(maxy)s,
                                                            %(minx)s %(maxy)s,
                                                            %(minx)s %(miny)s))',%(db_srid)s))"""
            msg = 'Created new extent for package %s' 

        conn.execute(statement,params)

        Session.commit()
        log.info(msg, package.id)
        return package
    except:
        log.error('An error occurred when saving the extent for package %s',package.id)
        raise Exception