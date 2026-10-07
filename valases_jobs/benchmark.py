"""Repeatable synthetic algorithm smoke benchmark, not a production quality claim."""
import argparse
import json
import time
from valases_jobs.matching import match_jobs

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--jobs',type=int,default=100000)
    args=parser.parse_args()
    templates=[{'title':'Python Developer','skills':['Python','SQL','Git']},
               {'title':'Accountant','skills':['Tally','GST','Excel']},
               {'title':'Recruiter','skills':['Recruitment','Payroll']},
               {'title':'Sales Executive','skills':['CRM','Lead generation']},
               {'title':'Frontend Developer','skills':['JavaScript','React','Git']}]
    jobs=[{**templates[i%len(templates)],'id':str(i),'location':'Bengaluru','work_arrangement':'hybrid'} for i in range(args.jobs)]
    started=time.perf_counter()
    matches=match_jobs('Developed Python and SQL APIs using Git and automated testing',{},jobs)
    elapsed=time.perf_counter()-started
    print(json.dumps({'synthetic_jobs':args.jobs,'matches':len(matches),'matching_seconds':round(elapsed,3),
                      'scope':'one process, synthetic catalog; excludes database, networking and concurrent users'}))

if __name__=='__main__': main()
