# -*- coding: utf-8 -*-
"""
    flaskext.extended_logging
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    Description of the module goes here...

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import traceback
from datetime import datetime
from flask import _request_ctx_stack
from logging import LoggerAdapter, Formatter


class LoggerWrapper(LoggerAdapter, object):
    """Wrapps a logger to inject additional variables into the
    format string automatically.

    The following extra values are added to the variables passed
    to the format string:

    =========================== =========================================
    ``%(http_path)s``           the current path below the application.
                                (eg: ``'/index'``).
    ``%(http_url)s``            the full URL for the request
                                (eg: ``'http://example.com/index'``)
    ``%(http_method)s``         the method that was used for the request.
                                (eg: ``'GET'``)
    ``%(http_remote_addr)s``    the remote address (eg: ``'127.0.0.1'``)
    ``%(http_user_agent)s``     the user agent of the request
    =========================== =========================================

    If values are unavailable (for example because the log entry was
    emitted from a background thread that was not request bound) the
    value will be an empty string (``''``).
    """

    def __init__(self, logger):
        LoggerAdapter.__init__(self, logger, {})
        self.extra_handlers = []

    @property
    def inject(self, f):
        """Registers a function that is passed a dictionary with values
        it can extend to add additional log information to the record
        that can then be used by the log formatter.

        Here an example that logs the active user::

            @app.logger.inject
            def log_user(d, ctx):
                d['app_user'] = 'anonymous'
                if ctx is not None and ctx.g.user is not None:
                    d['app_user'] = ctx.g.user.username

        The second parameter passed is the request context that was used
        to trigger the log record.  If no request context was available,
        it will be `None`.  Note that you always have to set a key so
        that the formatter later will not raise a :exc:`KeyError`.
        """
        self.extra_handlers.append(f)
        return f

    def process(self, msg, kwargs):
        msg, kwargs = LoggerAdapter.process(self, msg, kwargs)
        path = method = remote_addr = user_agent = url = u''
        ctx = _request_ctx_stack.top
        if ctx is not None:
            path = ctx.request.path
            url = ctx.request.url
            method = ctx.request.method
            remote_addr = ctx.request.remote_addr
            user_agent = ctx.request.headers.get('user-agent', u'')
        kwargs['extra'].update(
            http_path=path,
            http_url=url,
            http_method=method,
            http_remote_addr=remote_addr,
            http_user_agent=user_agent
        )
        for handler in self.extra_handlers:
            handler(kwargs['extra'], ctx)
        return msg, kwargs


class _ExceptionInfo(object):

    def __init__(self, exc_info):
        self._exc_info = exc_info

    def __nonzero__(self):
        return self._exc_info is not None

    @property
    def exception_object(self):
        if self._exc_info:
            return self._exc_info[1]

    @property
    def exception(self):
        if self._exc_info is None:
            return u''
        lines = traceback.format_exception_only(*self._exc_info[:2])
        rv = ''.join(lines).decode('utf-8', 'replace')
        return rv.rstrip()

    @property
    def traceback(self):
        if self._exc_info is None:
            return u''
        lines = traceback.format_exception(*self._exc_info)
        rv = ''.join(lines).decode('utf-8', 'replace')
        return rv.rstrip()

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __unicode__(self):
        return self.traceback


class TemplatedFormatter(Formatter, object):
    """Works like a regular log formatter but uses Jinja2 templates
    for log entry formatting.  This has the huge advantage that it's
    possible to conditionally format entries which is very handy for
    mail notifications and similar notification types.

    Example::

        mail_handler = logging.SMTPHandler('127.0.0.1',
                                           'server-error@example.com',
                                           ADMINS, 'Application Failed')
        mail_handler.setFormatter(TemplatedFormatter(app, template_string='''\
        Message type:       {{ levelname }}
        Location:           {{ pathname }}:{{ lineno }}
        Module:             {{ module }}
        Function:           {{ funcName }}
        Time:               {{ time }}
        {%- if http_url %}
        Request URL:        {{ http_url }} [{{ http_method or 'UNKNOWN' }}]
        {%- endif %}

        Message:

        {{ message }}

        {%- if exc_info %}

        Traceback:

        {{ exc_info }}
        {%- endif %}
        '''))
        app.logger.addHandler(mail_handler)
    """

    def __init__(self, app, template_name=None, template_string=None):
        Formatter.__init__(self)
        self.app = app
        self.template_name = template_name
        self.template_string = template_string
        self._template = None

    @property
    def template(self):
        if self._template is not None:
            return self._template
        if self.template_name is not None:
            return self.app.jinja_env.get_template(self.template_name)
        self._template = self.app.jinja_env.from_string(self.template_string)
        return self._template

    def format(self, record):
        context = {}
        for key, value in record.__dict__.iteritems():
            # cache keys and other things that might have been attached by
            # another log formatter before.  We get rid of that first.
            if key in ('exc_text', 'asctime'):
                continue
            # we pass datetime objects to jinja, they are easier to handle.
            if key == 'created':
                value = datetime(*value[:7])
            # make sure strings are unicode
            if isinstance(value, str):
                value = value.decode('utf-8', 'replace')
            context[key] = value

        # the exception information is an object with a few methods to
        # test and format exceptions
        context['exc_info'] = _ExceptionInfo(context.get('exc_info'))
        return self.template.render(context)


def init_extended_logging(app):
    """Activates extended logging for the given application."""
    app.logger = LoggerWrapper(app.logger)
