"""Run standard-library unit/integration tests and save machine-readable evidence."""
import argparse
import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records=[]
    def startTest(self,test):self.started=time.perf_counter();super().startTest(test)
    def record(self,test,status,detail=''):
        fn=getattr(test,getattr(test,'_testMethodName',''),None)
        self.records.append(dict(test=test.id(),case_id=getattr(fn,'case_id',test.id()),status=status,seconds=round(time.perf_counter()-self.started,4),actual=detail or 'Các assertion đã chạy và đạt.',executed_at=datetime.now(timezone.utc).isoformat()))
    def addSuccess(self,test):super().addSuccess(test);self.record(test,'Passed')
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,'Failed',self._exc_info_to_string(err,test))
    def addError(self,test,err):super().addError(test,err);self.record(test,'Failed',self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,'Blocked',reason)

def run(output='test-results/results.json'):
    root=Path(__file__).parent
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),top_level_dir=str(root))
    began=datetime.now(timezone.utc).isoformat();timer=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite)
    payload=dict(started_at=began,duration_seconds=round(time.perf_counter()-timer,3),total=result.testsRun,passed=sum(r['status']=='Passed' for r in result.records),failed=len(result.failures)+len(result.errors),skipped=len(result.skipped),cases=result.records)
    target=root/output;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return result.wasSuccessful()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='test-results/results.json');a=p.parse_args()
    raise SystemExit(0 if run(a.output) else 1)
