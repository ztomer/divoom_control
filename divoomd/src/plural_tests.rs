use crate::plural::{counted, counted_as, noun, noun_as};

#[test]
fn exactly_one_is_singular() {
    assert_eq!(counted(1, "file"), "1 file");
    assert_eq!(counted(0, "file"), "0 files");
    assert_eq!(counted(2, "file"), "2 files");
    assert_eq!(noun(1, "device"), "device");
    assert_eq!(noun(4, "device"), "devices");
}

#[test]
fn an_irregular_plural_is_named() {
    assert_eq!(counted_as(1, "entry", "entries"), "1 entry");
    assert_eq!(counted_as(3, "entry", "entries"), "3 entries");
    assert_eq!(noun_as(0, "process", "processes"), "processes");
}
