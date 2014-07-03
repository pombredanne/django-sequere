from django.test.utils import override_settings
from django.test import TestCase
from django.core.urlresolvers import reverse

from exam.decorators import fixture
from exam.cases import Exam

from .models import Project

from sequere import settings
from sequere.registry import registry
from sequere.http import json
from sequere.backends.database.models import Follow


class FixturesMixin(Exam):
    @fixture
    def user(self):
        from ..compat import User

        return User.objects.create_user(username='thoas',
                                        email='florent@ulule.com',
                                        password='$ecret')

    @fixture
    def user2(self):
        from ..compat import User

        return User.objects.create_user(username='louisegrandjonc',
                                        email='louise@ulule.com',
                                        password='$uperPassword')
        
    @fixture
    def user3(self):
        from ..compat import User

        return User.objects.create_user(username='brogol',
                                        email='yohann@ulule.com',
                                        password='$uperPassword')

    @fixture
    def project(self):
        return Project.objects.create(name='My super project')


class BaseBackendTests(FixturesMixin):
    def test_follow(self):
        from ..models import follow, get_followings_count, get_followers_count

        follow(self.user, self.project)

        self.assertEqual(get_followings_count(self.user), 1)

        self.assertEqual(get_followings_count(self.user, registry.get_identifier(self.project)), 1)

        self.assertEqual(get_followers_count(self.project), 1)

        self.assertEqual(get_followers_count(self.project, registry.get_identifier(self.user)), 1)

    def test_unfollow(self):
        from ..models import (follow, get_followings_count,
                              get_followers_count, unfollow)

        follow(self.user, self.project)

        unfollow(self.user, self.project)

        self.assertEqual(get_followings_count(self.user), 0)

        self.assertEqual(get_followings_count(self.user, registry.get_identifier(self.project)), 0)

        self.assertEqual(get_followers_count(self.project), 0)

        self.assertEqual(get_followers_count(self.project, registry.get_identifier(self.user)), 0)

    def test_friends(self):
        from ..models import (follow, get_friends_count,
                              unfollow)

        follow(self.user, self.project)

        self.assertEqual(get_friends_count(self.user), 0)

        follow(self.project, self.user)

        from_identifier = registry.get_identifier(self.user)
        to_identifier = registry.get_identifier(self.project)

        self.assertEqual(get_friends_count(self.user), 1)
        self.assertEqual(get_friends_count(self.user, to_identifier), 1)
        self.assertEqual(get_friends_count(self.user, from_identifier), 0)
        self.assertEqual(get_friends_count(self.project), 1)
        self.assertEqual(get_friends_count(self.project, from_identifier), 1)
        self.assertEqual(get_friends_count(self.project, to_identifier), 0)

        unfollow(self.user, self.project)

        self.assertEqual(get_friends_count(self.project), 0)
        self.assertEqual(get_friends_count(self.user), 0)

    def test_get_friends(self):
        pass

    def test_is_following(self):
        from ..models import (follow, unfollow, is_following)

        follow(self.user, self.project)

        self.assertTrue(is_following(self.user, self.project))

        unfollow(self.user, self.project)

        self.assertFalse(is_following(self.user, self.project))

    def test_get_followers(self):
        from ..models import follow, get_followers

        follow(self.user, self.project)

        qs = get_followers(self.project)

        self.assertEqual(qs.count(), 1)

        self.assertIn(self.user, dict(qs.all()))

    def test_get_followings(self):
        from ..models import follow, get_followings

        follow(self.user, self.project)

        qs = get_followings(self.user)

        self.assertEqual(qs.count(), 1)

        self.assertIn(self.project, dict(qs.all()))

    def test_follow_view(self):
        user = self.user

        self.client.login(username=user.username, password='$ecret')

        response = self.client.post(reverse('sequere_follow'))

        self.assertEqual(response.status_code, 400)

        response = self.client.post(reverse('sequere_follow'), data={
            'identifier': 'not-an-identifier',
            'object_id': 1
        })

        self.assertEqual(response.status_code, 400)

        project = self.project

        identifier = registry.get_identifier(project)

        response = self.client.post(reverse('sequere_follow'), data={
            'identifier': identifier,
            'object_id': project.pk
        })

        self.assertEqual(response.status_code, 200)

        content = json.loads(response.content)

        self.assertEqual(content['followings_count'], 1)
        self.assertEqual(content['%s_followings_count' % identifier], 1)

    def test_unfollow_view(self):
        from ..models import follow

        user = self.user

        self.client.login(username=user.username, password='$ecret')

        response = self.client.post(reverse('sequere_follow'))

        project = self.project

        follow(self.user, project)

        identifier = registry.get_identifier(project)

        response = self.client.post(reverse('sequere_unfollow'), data={
            'identifier': identifier,
            'object_id': project.pk
        })

        self.assertEqual(response.status_code, 200)

        content = json.loads(response.content)

        self.assertEqual(content['followings_count'], 0)
        self.assertEqual(content['%s_followings_count' % identifier], 0)

    def test_is_friend(self):
        from ..models import follow, is_friend

        user = self.user
        user2 = self.user2

        self.assertFalse(is_friend(user, user2))

        follow(self.user, self.user2)
        follow(self.user2, self.user)

        self.assertTrue(is_friend(self.user, self.user2))

    def test_get_degree(self):
        from ..models import follow, get_degree

        user = self.user
        user2 = self.user2
        user3 = self.user3

        follow(user, user2)
        follow(user2, user)

        # Friends
        self.assertEqual(get_degree(user, user2), 0)
        # Not friends
        self.assertEqual(get_degree(user, user3), 3)

        follow(user2, user3)
        follow(user3, user2)

        self.assertEqual(get_degree(user, user3), 1)

    def test_get_related_friends(self):
        from ..models import follow, get_related_friends

        user = self.user
        user2 = self.user2
        user3 = self.user3

        follow(user, user2)
        follow(user2, user)

        # Friends
        self.assertEqual(len(get_related_friends(user, 1)), 0)
        # Not friends

        follow(user2, user3)
        follow(user3, user2)

        self.assertEqual(len(get_related_friends(user, 1)), 1)

        self.assertTrue(user3 in get_related_friends(user, 1))


@override_settings(SEQUERE_BACKEND_CLASS='sequere.backends.database.DatabaseBackend')
class DatabaseBackendTests(BaseBackendTests, TestCase):
    def setUp(self):
        super(DatabaseBackendTests, self).setUp()

        reload(settings)

    def test_from_instance_and_to_instance(self):
        from ..models import follow

        follow(self.user, self.project)

        instance = Follow.objects.all()[0]

        self.assertEqual(instance.to_instance, self.project)
        self.assertEqual(instance.from_instance, self.user)


@override_settings(SEQUERE_BACKEND_CLASS='sequere.backends.redis.RedisBackend')
class RedisBackendTests(BaseBackendTests, TestCase):
    def setUp(self):
        super(RedisBackendTests, self).setUp()

        reload(settings)

        from sequere.backends import get_backend

        get_backend()().client.flushdb()
