import unittest
from plug_totals_policy import select

class TotalsPolicyTests(unittest.TestCase):
    def test_follow(self):
        self.assertEqual(select('Under',48,48.9)['side'],'Over')
        self.assertEqual(select('Over',48,47.1)['side'],'Under')
    def test_fade(self):
        self.assertEqual(select('Over',48,49)['side'],'Under')
        self.assertEqual(select('Under',48,47)['side'],'Over')
    def test_fallback(self):
        self.assertEqual(select('Over',47.5,55)['side'],'Over')
        self.assertEqual(select('Under',48,48)['side'],'Under')
        self.assertEqual(select('Over',48,None)['side'],'Over')
    def test_invalid(self):
        for bad in (float('nan'),float('inf'),True,'49',5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                select('Under',bad,49)

if __name__=='__main__': unittest.main()
