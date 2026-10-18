//! A per-panel state cell that forgetting the panel closes for good (P5.9).
//!
//! A [`super::Device`] is shared by `Arc`: the fleet holds one, and so does
//! every request that looked the panel up and has not finished. When
//! `disconnect` forgets the panel, those holders still have it. P5.8 left
//! them free to keep writing: a `live_job_start` that looked the panel up
//! just before the removal installed its job just after, on a device nobody
//! could list or stop. A closed slot has no room for a value, so "a live job
//! on a forgotten panel" is a state the type cannot hold -- whoever holds
//! the `Arc`, and whenever they get to it.

pub(super) enum Slot<T> {
    Open(Option<T>),
    Closed,
}

impl<T> Slot<T> {
    pub(super) const fn empty() -> Self {
        Self::Open(None)
    }

    pub(super) const fn get(&self) -> Option<&T> {
        match self {
            Self::Open(v) => v.as_ref(),
            Self::Closed => None,
        }
    }

    pub(super) const fn get_mut(&mut self) -> Option<&mut T> {
        match self {
            Self::Open(v) => v.as_mut(),
            Self::Closed => None,
        }
    }

    pub(super) const fn take(&mut self) -> Option<T> {
        match self {
            Self::Open(v) => v.take(),
            Self::Closed => None,
        }
    }

    /// Close for good, returning what was in it.
    pub(super) fn close(&mut self) -> Option<T> {
        match std::mem::replace(self, Self::Closed) {
            Self::Open(v) => v,
            Self::Closed => None,
        }
    }

    /// Put `v` in, returning what it replaced; `Err(v)` once closed, so the
    /// caller still owns it and must dispose of it.
    pub(super) const fn replace(&mut self, v: T) -> Result<Option<T>, T> {
        match self {
            Self::Open(old) => Ok(old.replace(v)),
            Self::Closed => Err(v),
        }
    }

    /// The value, made by `make` when empty; `None` once closed.
    pub(super) fn get_or_insert_with(&mut self, make: impl FnOnce() -> T) -> Option<&mut T> {
        match self {
            Self::Open(v) => Some(v.get_or_insert_with(make)),
            Self::Closed => None,
        }
    }
}
