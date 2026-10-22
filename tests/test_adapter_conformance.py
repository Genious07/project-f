import unittest

from foresee.catalog_conformance import CatalogFixture
from foresee.conformance import adapter_suite


class ContractKitTests(unittest.TestCase):
    def probe(self, fixture, method):
        suite = adapter_suite(fixture, 'Broken')
        selected = unittest.TestSuite(test for test in suite if test._testMethodName == method)
        result = unittest.TestResult()
        selected.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertFalse(result.wasSuccessful(), 'kit accepted a broken adapter fixture')

    def test_detects_missing_receipts(self):
        class MissingReceipts(CatalogFixture):
            def receipts(self):
                return []
        self.probe(MissingReceipts, 'test_commit_persists_rows_revision_and_receipt')

    def test_detects_simulation_writes(self):
        class WritesDuringSimulation(CatalogFixture):
            def simulate(self, base, plan):
                self.mutate()
                return super().simulate(base, plan)
        self.probe(WritesDuringSimulation, 'test_simulation_does_not_write')

    def test_detects_missing_fault_boundaries(self):
        class NoFaults(CatalogFixture):
            def connect(self):
                adapter = super().connect()
                commit = adapter.commit
                adapter.commit = lambda *args, **kwargs: commit(*args, **{k: v for k, v in kwargs.items() if k != 'fault_hook'})
                return adapter
        self.probe(NoFaults, 'test_precommit_faults_hide_and_rollback_writes')


def load_tests(loader, tests, pattern):
    tests.addTests(adapter_suite(CatalogFixture, 'SQLiteCatalog'))
    return tests
