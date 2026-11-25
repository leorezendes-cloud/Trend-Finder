"""Newsletter Expert teaser regressions."""
import unittest
from newsletter_draft import _expert_newsletter_story


class ExpertNewsletterStoryTests(unittest.TestCase):
    def test_uses_approved_summary_and_real_picks(self):
        report = {'summary': ('Dallas has the stronger passing attack, while Philadelphia '
                              'has struggled to score lately. The Eagles could keep this '
                              'close with defense, but Dallas has the better offense.'),
                  'ats_side': 'DAL', 'total_side': None, 'sections': []}
        story = _expert_newsletter_story(report)
        self.assertIn('Dallas has the stronger passing attack', story)
        self.assertIn('likes DAL against the spread', story)
        self.assertIn('The Expert is passing on the total', story)
        self.assertNotIn('Read The Expert’s full football take', story)

    def test_no_literal_newline_or_repeated_pick(self):
        report = {'summary': ('Dallas can separate through the air. I like Dallas against '
                              'the number. On the total, I’d pass rather than guess.'),
                  'ats_side': 'DAL', 'total_side': None}
        story = _expert_newsletter_story(report)
        self.assertNotIn('\\\\n', story)
        self.assertNotIn('The Expert likes DAL', story)
        self.assertNotIn('The Expert is passing on the total', story)

    def test_fallback_uses_final_verdict_without_inventing_pick(self):
        report = {'summary': '', 'sections': [
            {'heading': 'The Expert’s Final Verdict',
             'text': 'I like the underdog to stay close in a physical game.'}],
            'ats_side': None, 'total_side': 'Under'}
        story = _expert_newsletter_story(report)
        self.assertIn('physical game', story)
        self.assertIn('passing on the spread', story)
        self.assertIn('likes Under', story)


if __name__ == '__main__':
    unittest.main()
