from sequere.registry import registry

from .utils import get_key


class Manager(object):
    def __init__(self, client, prefix=None):
        self.client = client
        self.prefix = prefix or ''

    def add_prefix(self, key):
        return get_key(self.prefix, key)

    def make_uid(self, data):
        uid = self.client.incr(self.add_prefix(get_key('global', 'uid')))

        data['uid'] = uid

        self.client.hmset(self.add_prefix(get_key('uid', uid)), data)

        return uid

    def get_data_from_uid(self, uid):
        return self.client.hgetall(self.add_prefix(get_key('uid', uid)))

    def clear(self):
        self.client.flushdb()


class InstanceManager(Manager):
    def make_uid(self, instance):
        uid = self.get_uid(instance)

        if not uid:
            identifier = registry.get_identifier(instance)

            uid = super(InstanceManager, self).make_uid({
                'identifier': identifier,
                'object_id': instance.pk
            })

            self.client.set(self.make_uid_key(instance), uid)

        return uid

    def make_uid_key(self, instance):
        identifier = registry.get_identifier(instance)

        object_id = instance.pk

        return self.add_prefix(get_key('uid', identifier, object_id))

    def get_from_uid(self, uid):
        data = self.get_data_from_uid(uid)

        klass = registry.identifiers.get(data['identifier'])

        return klass.objects.filter(pk=data['object_id']).first()

    def get_uid(self, instance):
        return self.client.get(self.make_uid_key(instance))