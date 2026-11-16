//! A fixture crate for sphinx-rustdoc's tests.
//!
//! # Overview
//!
//! Start with [`Client`], or see [`shapes::Shape`].

pub mod edge;
pub mod shapes;

mod inner;

pub use inner::Client;
pub use inner::ClientBuilder as Builder;
pub use shapes::Shape;
pub use std::collections::HashMap as Map;

/// Everything in [`shapes`], for a glob import.
pub mod prelude {
    pub use crate::shapes::*;
}

/// The answer.
pub const ANSWER: u32 = 42;

/// Three bytes.
pub const ARRAY: [u8; 3] = [1, 2, 3];

/// The crate's name.
pub static NAME: &str = "fixture";

/// Results from this crate.
pub type Result<T> = std::result::Result<T, Error>;

/// What can go wrong.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub enum Error {
    /// The resource doesn't exist.
    NotFound,
    /// The request timed out after this many seconds.
    Timeout(u64),
    /// The request failed.
    Failed {
        /// What the server said.
        message: String,
        /// The status code.
        code: i32,
    },
}

/// Add two numbers.
///
/// ```
/// # let hidden = 1;
/// ## let shown = 2;
/// assert_eq!(fixture::add(1, 2), 3);
/// ```
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

/// Find the first item, if any.
///
/// ```text
/// # not hidden: this block isn't Rust
/// ```
pub async fn first<'a, T>(items: &'a [T], key: impl AsRef<str>) -> Option<&'a T>
where
    T: Clone + Send + 'static,
{
    let _ = key.as_ref();
    items.first()
}

/// Apply functions.
pub fn apply(
    f: fn(i32) -> i32,
    g: &dyn Fn(&str) -> bool,
    mut h: Box<dyn Iterator<Item = u8> + Send>,
) -> (i32, bool) {
    (f(1), g("x") && h.next().is_some())
}

/// Use [`add`] instead.
#[deprecated(since = "0.2.0", note = "use `add`")]
pub fn old_add(a: i32, b: i32) -> i32 {
    a + b
}

/// An identifier.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Rid(pub u64);

/// Something with an ID.
pub trait Identified {
    /// The ID's type.
    type Id: Clone;

    /// How many IDs it has.
    const COUNT: usize = 1;

    /// The ID.
    fn id(&self) -> Self::Id;

    /// The ID as text.
    fn label(&self) -> String
    where
        Self::Id: std::fmt::Display,
    {
        self.id().to_string()
    }
}

/// Square a number.
#[macro_export]
macro_rules! square {
    ($x:expr) => {
        $x * $x
    };
}
