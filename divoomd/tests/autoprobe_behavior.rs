//! Autoprobe decision-flow parity: iOS-LE first, then Basic, default Basic.

use std::future::Future;
use std::pin::Pin;

use divoomd::autoprobe::{autoprobe, Prober, Protocol};

/// A mock prober that answers `true` only for the configured framing(s).
struct Mock {
    ios_le_answers: bool,
    basic_answers: bool,
}

impl Prober for Mock {
    fn probe<'a>(&'a self, framing: Protocol) -> Pin<Box<dyn Future<Output = bool> + Send + 'a>> {
        let ans = match framing {
            Protocol::IosLe => self.ios_le_answers,
            Protocol::Basic => self.basic_answers,
        };
        Box::pin(async move { ans })
    }
}

#[tokio::test]
async fn detects_ios_le_when_it_answers() {
    let m = Mock {
        ios_le_answers: true,
        basic_answers: false,
    };
    assert_eq!(autoprobe(&m).await, Protocol::IosLe);
}

#[tokio::test]
async fn falls_back_to_basic_when_only_basic_answers() {
    let m = Mock {
        ios_le_answers: false,
        basic_answers: true,
    };
    assert_eq!(autoprobe(&m).await, Protocol::Basic);
}

#[tokio::test]
async fn defaults_to_basic_when_neither_answers() {
    let m = Mock {
        ios_le_answers: false,
        basic_answers: false,
    };
    assert_eq!(autoprobe(&m).await, Protocol::Basic);
}

#[tokio::test]
async fn prefers_ios_le_when_both_answer() {
    // iOS-LE is probed first, so it wins even if Basic would also answer.
    let m = Mock {
        ios_le_answers: true,
        basic_answers: true,
    };
    assert_eq!(autoprobe(&m).await, Protocol::IosLe);
}
