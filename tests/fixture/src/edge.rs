//! Cases rustdoc allows that are easy to get wrong.

/// Counts things. Count with [the counter][Counter] or [`Counter`][].
///
/// > ```no_run
/// > # let quoted_hidden = 1;
/// > let quoted = 2;
/// > ```
///
/// An indented block:
///
///     # let hidden = 1;
///     let indented = 2;
pub struct Counter {
    /// The count so far.
    pub count: u32,
}

impl Counter {
    /// The count, as a method of the same name as the field.
    pub fn count(&self) -> u32 {
        self.count
    }
}

/// A module with the same name as a function.
pub mod total {}

/// A function with the same name as a module.
///
/// # Examples
///
/// See [the examples](#examples): use [`Level::Low`] or [`Low`].
pub fn total() -> u32 {
    0
}

/// Another function whose docs have the same heading.
///
/// # Examples
///
/// See [the examples](#examples).
pub fn subtotal() -> u32 {
    0
}

/// A level.
pub enum Level {
    /// Low.
    Low,
    /// High.
    High,
}

pub use Level::Low;

mod imp {
    /// Reachable only through re-exports.
    pub struct Deep;
}

mod private {
    pub mod hub {
        pub use crate::edge::imp::Deep;
    }
}

pub use private::hub as shortcut;

/// Nested modules.
pub mod a {
    /// A nested module.
    pub mod b {
        pub use super::super::imp::Deep;
    }
}
