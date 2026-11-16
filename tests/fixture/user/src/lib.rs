//! Uses the fixture crate.

/// Make a [`fixture::Client`].
pub fn client() -> fixture::Client {
    fixture::Client::new("https://example.com")
}
