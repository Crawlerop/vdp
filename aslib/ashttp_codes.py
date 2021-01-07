from enum import IntEnum

__all__ = ['HTTPStatus']

class HTTPStatus(IntEnum):
    """HTTP status codes and reason phrases

    Status codes from the following RFCs are all observed:

        * RFC 7231: Hypertext Transfer Protocol (HTTP/1.1), obsoletes 2616
        * RFC 6585: Additional HTTP Status Codes
        * RFC 3229: Delta encoding in HTTP
        * RFC 4918: HTTP Extensions for WebDAV, obsoletes 2518
        * RFC 5842: Binding Extensions to WebDAV
        * RFC 7238: Permanent Redirect
        * RFC 2295: Transparent Content Negotiation in HTTP
        * RFC 2774: An HTTP Extension Framework
        * RFC 7725: An HTTP Status Code to Report Legal Obstacles
        * RFC 7540: Hypertext Transfer Protocol Version 2 (HTTP/2)
    """
    def __new__(cls, value, phrase='', description='', s=""):
        obj = int.__new__(cls, value)
        obj._value_ = value

        obj.phrase = phrase
        obj.description = description
        return obj

    # informational
    CONTINUE = 100, 'Continue', 'Request received, please continue'
    SWITCHING_PROTOCOLS = (101, 'Switching Protocols',
            'Switching to new protocol; obey Upgrade header')
    PROCESSING = 102, 'Processing'
    EARLY_HINTS = 103, 'Early Hints'

    # success
    OK = 200, 'OK', 'All systems OK!'
    CREATED = 201, 'Created', 'New document!'
    ACCEPTED = (202, 'Accepted',
        'Processing will done asynchronously!')
    NON_AUTHORITATIVE_INFORMATION = (203,
        'Non-Authoritative Information', 'Intercepted requests will follow!')
    NO_CONTENT = 204, 'No Content', 'Nothing there'
    RESET_CONTENT = 205, 'Reset Content', 'Input was reset!'
    PARTIAL_CONTENT = 206, 'Partial Content', 'Byte-Range header was requested! Let this file will be chunked!'
    MULTI_STATUS = 207, 'Multi-Status'
    ALREADY_REPORTED = 208, 'Already Reported'
    IM_USED = 226, 'IM Used'

    # redirection
    MULTIPLE_CHOICES = (300, 'Multiple Choices',
        'There\'s multiple choices for this redirection.')
    MOVED_PERMANENTLY = (301, 'Moved Permanently',
        'This page has moved')
    FOUND = 302, 'Found', 'This page has moved'
    SEE_OTHER = 303, 'See Other', 'The answer has been located here.'
    NOT_MODIFIED = (304, 'Not Modified',
        'Cache is still fresh, you may now use this for performance.')
    USE_PROXY = (305, 'Use Proxy',
        'Proxy is now being used.')
    TEMPORARY_REDIRECT = (307, 'Temporary Redirect',
        'This page has moved')
    PERMANENT_REDIRECT = (308, 'Permanent Redirect',
        'This page has moved')

    # client error
    BAD_REQUEST = (400, 'Bad Request',
        'Invalid request')
    UNAUTHORIZED = (401, 'Unauthorized',
        'You are not allowed to access this page.',
        'Please login.')
    PAYMENT_REQUIRED = (402, 'Payment Required',
        'It\'s time to pay!')
    FORBIDDEN = (403, 'Forbidden',
        'You are not allowed to access this page.',
        'If you\'re think that this has been done as an error, please contact the site admin.')
    NOT_FOUND = (404, 'Not Found',
        'We couldn\'t find the page whatever you\'re looking for.')
    METHOD_NOT_ALLOWED = (405, 'Method Not Allowed',
        'No method matches this URI.')
    NOT_ACCEPTABLE = (406, 'Not Acceptable')
    PROXY_AUTHENTICATION_REQUIRED = (407,
        'Proxy Authentication Required',
        'Please login to the Proxy before continuing.')
    REQUEST_TIMEOUT = (408, 'Request Timeout',
        'Timeout')
    CONFLICT = 409, 'Conflict', 'Request conflict'
    GONE = (410, 'Gone',
        'This URI has been permanently removed from this server.')
    LENGTH_REQUIRED = (411, 'Length Required',
        'POST and PUT requires a Content-Length header to be set.')
    PRECONDITION_FAILED = (412, 'Precondition Failed',
        'Cache is not fresh, therefore should be refetched.')
    PAYLOAD_TOO_LARGE = (413, 'Payload Too Large',
        'Maximum size for request body has been exceeded.')
    URI_TOO_LONG = (414, 'URI Too Long',
        'Maximum size for request URI has been exceeded.')
    UNSUPPORTED_MEDIA_TYPE = (415, 'Unsupported Media Type',
        'Unknown request format')
    REQUESTED_RANGE_NOT_SATISFIABLE = (416,
        'Requested Range Not Satisfiable',
        'Wrong request range')
    EXPECTATION_FAILED = (417, 'Expectation Failed',
        'Unknown expect header')
    MISDIRECTED_REQUEST = (421, 'Misdirected Request',
        'Your client sents a request that the server cannot process.')
    UNPROCESSABLE_ENTITY = 422, 'Unprocessable Entity'
    LOCKED = 423, 'Locked'
    FAILED_DEPENDENCY = 424, 'Failed Dependency'
    UPGRADE_REQUIRED = 426, 'Upgrade Required', 'Upgrade was required to proceed.'
    PRECONDITION_REQUIRED = (428, 'Precondition Required',
        'The cache requires precondition to be set')
    TOO_MANY_REQUESTS = (429, 'Too Many Requests',
        'You\'re sending too much requests for a short period of time, Please stop!')
    REQUEST_HEADER_FIELDS_TOO_LARGE = (431,
        'Request Header Fields Too Large',
        'Header fields is too big to handle.')
    UNAVAILABLE_FOR_LEGAL_REASONS = (451,
        'Unavailable For Legal Reasons',
        'The government has not allowed you to access this resource.')

    # server errors
    INTERNAL_SERVER_ERROR = (500, 'Internal Server Error',
        'We\'ve encountered a problem!')
    NOT_IMPLEMENTED = (501, 'Not Implemented',
        'This request were not implemented.')
    BAD_GATEWAY = (502, 'Bad Gateway',
        'Our backend is failing!')
    SERVICE_UNAVAILABLE = (503, 'Service Unavailable',
        'Our backend failed!')
    GATEWAY_TIMEOUT = (504, 'Gateway Timeout',
        'Our backend is timing out!')
    HTTP_VERSION_NOT_SUPPORTED = (505, 'HTTP Version Not Supported',
        'There\'s no text-based HTTP beyond version 1.1')
    VARIANT_ALSO_NEGOTIATES = 506, 'Variant Also Negotiates'
    INSUFFICIENT_STORAGE = 507, 'Insufficient Storage'
    LOOP_DETECTED = 508, 'Loop Detected'
    NOT_EXTENDED = 510, 'Not Extended'
    NETWORK_AUTHENTICATION_REQUIRED = (511,
        'Network Authentication Required',
        'Welcome to your WIFI hotspot! please login!')
