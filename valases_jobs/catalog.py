"""Transactional snapshots and indexed skill retrieval for the candidate catalog."""
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException
from sqlalchemy import select,delete,func,insert
from valases_jobs.models import CatalogJob,CatalogSkill,CatalogState
from valases_jobs.matching import evidence

def refresh(db,bridge):
    # Fetch fully first. A failed connection never replaces a good snapshot with an empty one.
    jobs=bridge.jobs()
    # One synchronization writer across workers; pg advisory transaction lock.
    if db.bind.dialect.name=='postgresql':
        from sqlalchemy import text
        if not db.scalar(text('SELECT pg_try_advisory_xact_lock(794079)')): db.rollback();return False
    db.execute(delete(CatalogSkill));db.execute(delete(CatalogJob))
    job_rows=[];skill_rows=[]
    for job in jobs:
        skills=sorted(set(str(skill).strip().lower() for skill in job.get('skills',[]) if str(skill).strip()))
        job_rows.append(dict(id=job['id'],payload=job,
            search_text=' '.join([job.get('title',''),job.get('company',''),*skills]).lower(),
            location=(job.get('location') or '').lower(),arrangement=job.get('work_arrangement') or '',
            employment_type=job.get('employment_type') or ''))
        skill_rows.extend([dict(job_id=job['id'],skill=skill) for skill in skills if len(skill)<=200])
        if len(job_rows)>=1000:
            db.execute(insert(CatalogJob),job_rows);db.execute(insert(CatalogSkill),skill_rows) if skill_rows else None
            job_rows=[];skill_rows=[]
    if job_rows:
        db.execute(insert(CatalogJob),job_rows);db.execute(insert(CatalogSkill),skill_rows) if skill_rows else None
    state=db.get(CatalogState,1)
    if not state: state=CatalogState(id=1);db.add(state)
    state.synced_at=datetime.now(timezone.utc);db.commit();return True

def require_fresh(db):
    state=db.get(CatalogState,1)
    if not state or state.synced_at.replace(tzinfo=timezone.utc)<datetime.now(timezone.utc)-timedelta(minutes=10):
        raise HTTPException(503,'Job catalog is synchronizing. Please retry shortly.')

def search(db,q='',location='',arrangement='',employment_type='',offset=0,limit=50):
    require_fresh(db)
    filters=[]
    if q:
        if db.bind.dialect.name=='postgresql':
            from sqlalchemy import text
            filters.append(text("to_tsvector('simple', search_text) @@ plainto_tsquery('simple', :catalog_query)").bindparams(catalog_query=q))
        else: filters.append(CatalogJob.search_text.contains(q.lower(),autoescape=True))
    if location: filters.append(CatalogJob.location.contains(location.lower(),autoescape=True))
    if arrangement: filters.append(CatalogJob.arrangement.in_(arrangement.split(',')))
    if employment_type: filters.append(CatalogJob.employment_type.in_(employment_type.split(',')))
    total=db.scalar(select(func.count()).select_from(CatalogJob).where(*filters))
    rows=db.scalars(select(CatalogJob).where(*filters).order_by(CatalogJob.id).offset(offset).limit(limit))
    return {'items':[row.payload for row in rows],'total':total,'offset':offset,'limit':limit}

def candidates(db,resume):
    require_fresh(db)
    # Vocabulary is much smaller than the catalog. The indexed join loads only roles
    # with supported skill evidence; matching then applies candidate preferences.
    skills=list(db.scalars(select(CatalogSkill.skill).distinct()))
    found=[skill for skill in skills if evidence(resume,skill)]
    if not found:return []
    ids=select(CatalogSkill.job_id).where(CatalogSkill.skill.in_(found)).distinct()
    return [row.payload for row in db.scalars(select(CatalogJob).where(CatalogJob.id.in_(ids)))]
