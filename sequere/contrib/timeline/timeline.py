import six

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone as datetime

from sequere.utils import get_client, to_timestamp, from_timestamp
from sequere.registry import registry
from sequere.backends.redis.managers import InstanceManager, Manager
from sequere.backends.redis.utils import get_key

from . import settings
from . import signals
from .query import TimelineQuerySetTransformer
from .tasks import dispatch_action

from .action import Action


class Timeline(object):
    def __init__(self, instance, *args, **kwargs):
        self.instance = instance
        self.prefix = kwargs.pop('prefix', settings.TIMELINE_PREFIX)
        self.kwargs = kwargs.pop('kwargs', {})

        connection_class = kwargs.pop('connection_class', settings.TIMELINE_CONNECTION_CLASS)

        nydus_connection = settings.TIMELINE_NYDUS_CONNECTION

        if nydus_connection:
            try:
                from nydus.db import create_cluster
            except ImportError:
                raise ImproperlyConfigured(
                    "The nydus backend requires nydus to be installed.")
            else:
                self.client = create_cluster(nydus_connection)
        else:
            self.client = get_client(settings.TIMELINE_CONNECTION, connection_class=connection_class)

        manager_class = kwargs.pop('manager_class', InstanceManager)

        self.manager = manager_class(get_client(settings.CONNECTION, connection_class=connection_class),
                                     prefix=settings.PREFIX)

        storage_class = kwargs.pop('storage_class', Manager)

        self.storage = storage_class(self.client,
                                     prefix=self.prefix)

    def _get_keys(self, action):
        identifier = registry.get_identifier(self.instance)

        prefix = self.storage.add_prefix('uid')

        uid = self.manager.make_uid(self.instance)

        keys = [
            get_key(prefix, uid, 'private'),
            get_key(prefix, uid, 'private', 'target', identifier)
        ]

        if action.actor == self.instance:
            keys.append(get_key(prefix, uid, 'public'))
            keys.append(get_key(prefix, uid, 'public', 'target', identifier))

        if action.target is not None and action.target != action.actor:
            identifier = registry.get_identifier(action.target)

            keys.append(get_key(prefix, action.actor_uid, 'private', 'target', identifier))

            if action.actor == self.instance:
                keys.append(get_key(prefix, action.actor_uid, 'public', 'target', identifier))

        return keys

    def _make_key(self, name, action=None, target=None):
        segments = [
            self.storage.add_prefix('uid'),
            self.manager.make_uid(self.instance),
            name,
        ]

        if target:
            if isinstance(target, six.string_types):
                segments += ['target', target]

            else:
                if isinstance(target, models.Model) or issubclass(target, models.Model):
                    segments += ['target', registry.get_identifier(target)]

        if action:
            if isinstance(action, six.string_types):
                segments += ['verb', action]
            elif issubclass(action, Action):
                segments += ['verb', action.verb]

        key = get_key(*segments)

        return key

    def _get_count(self, name, action=None, target=None):
        key = get_key(self._make_key(name, action=action, target=target), 'count')

        result = self.client.get(key)

        if result:
            return int(result)

        return 0

    def retrieve_instances(self, key, count, desc):
        transformer = TimelineQuerySetTransformer(self.client,
                                                  count,
                                                  key=key,
                                                  manager=self.manager,
                                                  prefix=self.prefix)
        transformer.order_by(desc)

        return transformer

    def _get_read_key(self):
        segments = [
            self.storage.add_prefix('uid'),
            self.manager.make_uid(self.instance),
            'read_at'
        ]

        return get_key(*segments)

    def mark_as_read(self, timestamp=None):
        if timestamp is None:
            timestamp = datetime.now()

        self.client.set(self._get_read_key(), to_timestamp(timestamp))

    @property
    def read_at(self):
        result = self.client.get(self._get_read_key())

        if result:
            return from_timestamp(float(result))

        return None

    def get_private(self, action=None, target=None, desc=True):
        key = self._make_key('private', action=action, target=target)

        return self.retrieve_instances(key, self.get_private_count(action=action, target=target), desc=desc)

    def get_public(self, action=None, target=None, desc=True):
        key = self._make_key('public', action=action, target=target)

        return self.retrieve_instances(key, self.get_private_count(action=action, target=target), desc=desc)

    def get_private_count(self, action=None, target=None, desc=True):
        return self._get_count('private', action=action, target=target)

    def get_public_count(self, action=None, target=None, desc=True):
        return self._get_count('public', action=action, target=target)

    def _save(self, action, data):
        with self.client.pipeline() as pipe:
            for key in self._get_keys(action):
                pipe.incr(get_key(key, 'count'))
                pipe.incr(get_key(key, 'verb', data['verb'], 'count'))

                pipe.zadd(key, **{
                    '%s' % action.uid: data['timestamp']
                })

                pipe.zadd(get_key(key, 'verb', data['verb']), **{
                    '%s' % action.uid: data['timestamp']
                })

            pipe.execute()

    def save(self, action, dispatch=True):
        from sequere.models import get_followers_count

        origin = action.__class__

        if dispatch:
            signals.pre_save.send(sender=origin,
                                  instance=self.instance,
                                  action=action)

        data = action.format_data(self.manager)

        if action.uid is None:
            uid = self.storage.make_uid(data)

            action.uid = uid

        self._save(action, data)

        if action.actor == self.instance and get_followers_count(self.instance):
            dispatch_action.delay(action.actor_uid, data)

        if dispatch:
            signals.post_save.send(sender=origin,
                                   instance=self.instance,
                                   action=action)
