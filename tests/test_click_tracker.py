import click_tracker


def test_increment_and_reset_counts():
    click_tracker.reset_counts()
    click_tracker.increment_keyboard()
    click_tracker.increment_keyboard()
    click_tracker.increment_mouse()

    assert click_tracker.get_counts() == (2, 1)

    click_tracker.reset_counts()
    assert click_tracker.get_counts() == (0, 0)
