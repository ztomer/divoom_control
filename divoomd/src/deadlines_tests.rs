//! The budget table names only real commands, and the slow ones are slow.

use super::*;

/// A budget keyed by a name the dispatcher does not answer is dead: the real
/// command falls back to the default and nothing says so. Read the dispatcher
/// itself rather than a second list of names that could drift from it.
#[test]
fn every_budgeted_command_is_a_dispatch_arm() {
    let dispatch = include_str!("daemon/dispatch.rs");
    for (name, _) in BUDGETS {
        assert!(
            dispatch.contains(&format!("\"{name}\" =>")),
            "deadline budget for `{name}`, which the dispatcher does not answer"
        );
    }
}

#[test]
fn a_slow_command_outlives_the_default_and_the_rest_get_it() {
    assert!(budget("sync_artwork") > DEFAULT_BUDGET);
    assert_eq!(budget("ping"), DEFAULT_BUDGET);
    for (_, d) in BUDGETS {
        assert!(*d >= DEFAULT_BUDGET, "a named budget below the default");
    }
}
