"""Check actual motor command serialization without GPIO, serial or hardware."""
import ast
from pathlib import Path
import unittest

source=ast.parse((Path(__file__).resolve().parents[1]/'services/motor.py').read_text())
cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='MotorService')
methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_send_drive','_keepalive_loop','_stop_motor'}]
namespace={}
exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])), '<motor methods>', 'exec'), namespace)
class Motor:
    _send_drive=namespace['_send_drive']
    _stop_motor=namespace['_stop_motor']
    def __init__(self): self.sent=[];self.success=True
    def _send_line(self,line):self.sent.append(line);return self.success
class Checks(unittest.TestCase):
    def test_legacy(self):
        m=Motor();m._send_drive(20,-20)
        self.assertEqual(m.sent,['DRIVE -51 51'])
        self.assertEqual(m._last_drive_command,m.sent[-1])
    def test_rate(self):
        m=Motor();m._send_drive(20,0,yaw_rate_dps=-19.481)
        self.assertEqual(m.sent,['TURNRATE 0 -19.481'])
        self.assertEqual(m._last_drive_command,m.sent[-1])
        m._stop_motor();self.assertIsNone(m._last_drive_command)
        self.assertEqual(m.sent[-1],'STOP')
    def test_failed_send(self):
        m=Motor();m.success=False
        self.assertFalse(m._send_drive(1,0,yaw_rate_dps=1))
        self.assertIsNone(m._last_drive_command)
if __name__=='__main__':unittest.main()
