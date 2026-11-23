"""Run all automated tests without using the application database."""
from pathlib import Path
import sys
import unittest

if __name__ == '__main__':
    folder = Path(__file__).resolve().parent
    sys.path.insert(0, str(folder))
    suite = unittest.defaultTestLoader.discover(str(folder), pattern='test_*.py', top_level_dir=str(folder))
    report = folder / 'test-results.txt'
    with report.open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    print(f'{result.testsRun} tests: {len(result.failures)} failures, {len(result.errors)} errors')
    print(f'Report: {report.name}')
    sys.exit(0 if result.wasSuccessful() else 1)
