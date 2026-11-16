use crate::{Identified, Rid};

/// A client.
///
/// Make one with [`Builder`](crate::Builder), then call [`Client::get`] or [`set_timeout`](Self::set_timeout).
///
/// # Examples
///
/// ```no_run
/// let client = fixture::Client::new("https://example.com");
/// ```
#[derive(Debug, Clone)]
pub struct Client {
    /// The base URL.
    pub base_url: String,
    timeout: u64,
}

impl Client {
    /// Make a client for `base_url`.
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            timeout: 30,
        }
    }

    /// Get a resource by its [`Rid`].
    ///
    /// # Errors
    ///
    /// [`Error::NotFound`](crate::Error::NotFound) if it doesn't exist.
    pub async fn get(&self, rid: Rid) -> crate::Result<String> {
        Ok(format!("{}/{}/{}", self.base_url, rid.0, self.timeout))
    }

    /// Set the timeout, in seconds.
    pub fn set_timeout(&mut self, seconds: u64) -> &mut Self {
        self.timeout = seconds;
        self
    }

    #[allow(dead_code)]
    fn private_helper(&self) {}
}

impl Identified for Client {
    type Id = String;

    fn id(&self) -> String {
        self.base_url.clone()
    }
}

impl std::fmt::Display for Client {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.base_url)
    }
}

/// Builds a [`Client`].
#[derive(Default)]
pub struct ClientBuilder<T = ()>
where
    T: Default,
{
    /// Anything extra.
    pub extra: T,
}

impl<T: Default> ClientBuilder<T> {
    /// Build the client.
    pub fn build(self) -> Client {
        Client::new("https://example.com")
    }
}
