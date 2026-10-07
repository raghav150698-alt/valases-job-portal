"""Bounded disposable parser subprocess. No uploaded files are persisted."""
import json
import subprocess
import sys
import os
from fastapi import HTTPException

def extract_text(content, suffix, timeout=15):
    if suffix not in {'.txt','.docx','.pdf'}: raise HTTPException(415,'Use a PDF, DOCX or UTF-8 TXT file')
    try:
        result=subprocess.run([sys.executable,'-m','valases_jobs.resume',suffix],input=content,
            capture_output=True,timeout=timeout,check=False,
            env={**{key:value for key,value in os.environ.items() if key.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}},'PYTHONDONTWRITEBYTECODE':'1'})
        data=json.loads(result.stdout)
    except (subprocess.TimeoutExpired,ValueError,OSError):
        raise HTTPException(422,'Document could not be read in time; paste resume text instead') from None
    if 'error' in data: raise HTTPException(data.get('status',422),data['error'])
    return data['text']

def parse(content,suffix):
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree
    if suffix=='.txt': text=content.decode('utf-8')
    elif suffix=='.docx':
        with ZipFile(BytesIO(content)) as archive:
            part=archive.getinfo('word/document.xml')
            if part.file_size>2*1024*1024: return {'error':'Expanded document is too large','status':413}
            xml=archive.read(part)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper(): return {'error':'Unsupported document markup'}
            root=ElementTree.fromstring(xml)
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            text='\n'.join(''.join(node.itertext()) for node in root.iter(ns+'p'))
    else:
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(content))
        if reader.is_encrypted: return {'error':'Use an unencrypted PDF'}
        if len(reader.pages)>15: return {'error':'Resume must have at most 15 pages','status':413}
        pages=[]
        for page in reader.pages:
            pages.append(page.extract_text() or '')
            if sum(map(len,pages))>120000: return {'error':'Extracted resume is too long','status':413}
        text='\n'.join(pages)
    if len(text)>120000: return {'error':'Extracted resume is too long','status':413}
    if len(text.strip())<20: return {'error':'No readable text found. Paste text for scanned resumes.'}
    return {'text':text}

if __name__=='__main__':
    try:
        if sys.platform!='win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU,(10,10))
        content=sys.stdin.buffer.read(2*1024*1024+1)
        data=parse(content,sys.argv[1]) if len(content)<=2*1024*1024 else {'error':'Resume too large','status':413}
    except Exception: data={'error':'Document could not be read; paste your resume text instead'}
    sys.stdout.write(json.dumps(data))
