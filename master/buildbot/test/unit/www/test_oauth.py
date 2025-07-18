# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

import json
import os
import warnings
import webbrowser
from unittest import mock

import twisted
import urllib3
from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet.threads import (
    deferToThread as twistedDeferToThread,
)  # import like this to avoid patching in other tests
from twisted.python import failure
from twisted.trial import unittest
from twisted.web.resource import Resource

import buildbot
from buildbot.process.properties import Secret
from buildbot.secrets.manager import SecretManager
from buildbot.test.fake.secrets import FakeSecretStorage
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.util import www
from buildbot.test.util.config import ConfigErrorsMixin
from buildbot.test.util.site import SiteWithClose

try:
    import requests
except ImportError:
    requests = None


if requests:
    from buildbot.www import oauth2  # pylint: disable=ungrouped-imports
else:
    oauth2 = None  # type: ignore[assignment]


class FakeResponse:
    def __init__(self, _json):
        self.json = lambda: _json
        self.content = json.dumps(_json)

    def raise_for_status(self):
        pass


class OAuth2Auth(TestReactorMixin, www.WwwTestMixin, ConfigErrorsMixin, unittest.TestCase):
    def setUp(self):
        self.setup_test_reactor()
        if requests is None:
            raise unittest.SkipTest("Need to install requests to test oauth2")

        self.patch(requests, 'request', mock.Mock(spec=requests.request))
        self.patch(requests, 'post', mock.Mock(spec=requests.post))
        self.patch(requests, 'get', mock.Mock(spec=requests.get))

    @defer.inlineCallbacks
    def setup_google_auth(self):
        auth = oauth2.GoogleAuth("ggclientID", "clientSECRET")
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth(self):
        auth = oauth2.GitHubAuth("ghclientID", "clientSECRET")
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth_v4(self):
        auth = oauth2.GitHubAuth("ghclientID", "clientSECRET", apiVersion=4)
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth_v4_secret(self):
        auth = oauth2.GitHubAuth(Secret("client-id"), Secret("client-secret"), apiVersion=4)
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        fake_storage_service = FakeSecretStorage()
        fake_storage_service.reconfigService(
            secretdict={"client-id": "secretClientId", "client-secret": "secretClientSecret"}
        )
        secret_service = SecretManager()
        secret_service.services = [fake_storage_service]
        yield secret_service.setServiceParent(master)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth_v4_teams(self):
        auth = oauth2.GitHubAuth(
            "ghclientID", "clientSECRET", apiVersion=4, getTeamsMembership=True
        )
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth_enterprise(self):
        auth = oauth2.GitHubAuth(
            "ghclientID", "clientSECRET", serverURL="https://git.corp.fakecorp.com"
        )
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_github_auth_enterprise_v4(self):
        auth = oauth2.GitHubAuth(
            "ghclientID",
            "clientSECRET",
            apiVersion=4,
            getTeamsMembership=True,
            serverURL="https://git.corp.fakecorp.com",
        )
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_gitlab_auth(self):
        auth = oauth2.GitLabAuth("https://gitlab.test/", "glclientID", "clientSECRET")
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def setup_bitbucket_auth(self):
        auth = oauth2.BitbucketAuth("bbclientID", "clientSECRET")
        master = yield self.make_master(url='h:/a/b/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def test_getGoogleLoginURL(self):
        auth = yield self.setup_google_auth()
        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://accounts.google.com/o/oauth2/auth?client_id=ggclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+"
            "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://accounts.google.com/o/oauth2/auth?client_id=ggclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+"
            "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile"
        )

        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getGithubLoginURL(self):
        auth = yield self.setup_github_auth()
        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://github.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://github.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getGithubLoginURL_with_secret(self):
        auth = yield self.setup_github_auth_v4_secret()
        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://github.com/login/oauth/authorize?client_id=secretClientId&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://github.com/login/oauth/authorize?client_id=secretClientId&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getGithubELoginURL(self):
        auth = yield self.setup_github_auth_enterprise()

        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://git.corp.fakecorp.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://git.corp.fakecorp.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getGithubLoginURL_v4(self):
        auth = yield self.setup_github_auth_enterprise_v4()

        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://git.corp.fakecorp.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://git.corp.fakecorp.com/login/oauth/authorize?client_id=ghclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&response_type=code&"
            "scope=user%3Aemail+read%3Aorg"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getGitLabLoginURL(self):
        auth = yield self.setup_gitlab_auth()

        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://gitlab.test/oauth/authorize"
            "?client_id=glclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&"
            "response_type=code&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://gitlab.test/oauth/authorize"
            "?client_id=glclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&"
            "response_type=code"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_getBitbucketLoginURL(self):
        auth = yield self.setup_bitbucket_auth()

        res = yield auth.getLoginURL('http://redir')
        exp = (
            "https://bitbucket.org/site/oauth2/authorize?"
            "client_id=bbclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&"
            "response_type=code&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "https://bitbucket.org/site/oauth2/authorize?"
            "client_id=bbclientID&"
            "redirect_uri=h%3A%2Fa%2Fb%2Fauth%2Flogin&"
            "response_type=code"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_GoogleVerifyCode(self):
        auth = yield self.setup_google_auth()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.get = mock.Mock(
            side_effect=[{"name": 'foo bar', "email": 'bar@foo', "picture": 'http://pic'}]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'avatar_url': 'http://pic',
                'email': 'bar@foo',
                'full_name': 'foo bar',
                'username': 'bar',
            },
            res,
        )

    @defer.inlineCallbacks
    def test_GithubVerifyCode(self):
        auth = yield self.setup_github_auth()

        test = self
        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]

        def fake_get(self, ep, **kwargs):
            test.assertEqual(
                self.headers,
                {
                    'Authorization': 'token TOK3N',
                    'User-Agent': f'buildbot/{buildbot.version}',
                },
            )
            if ep == '/user':
                return {"login": 'bar', "name": 'foo bar', "email": 'buzz@bar'}
            if ep == '/user/emails':
                return [
                    {'email': 'buzz@bar', 'verified': True, 'primary': False},
                    {'email': 'bar@foo', 'verified': True, 'primary': True},
                ]
            if ep == '/user/orgs':
                return [
                    {"login": 'hello'},
                    {"login": 'grp'},
                ]
            return None

        auth.get = fake_get

        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'email': 'bar@foo',
                'username': 'bar',
                'groups': ["hello", "grp"],
                'full_name': 'foo bar',
            },
            res,
        )

    @defer.inlineCallbacks
    def test_GithubVerifyCode_v4(self):
        auth = yield self.setup_github_auth_v4()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.post = mock.Mock(
            side_effect=[
                {
                    'data': {
                        'viewer': {
                            'organizations': {
                                'edges': [{'node': {'login': 'hello'}}, {'node': {'login': 'grp'}}]
                            },
                            'login': 'bar',
                            'email': 'bar@foo',
                            'name': 'foo bar',
                        }
                    }
                }
            ]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'email': 'bar@foo',
                'username': 'bar',
                'groups': ["hello", "grp"],
                'full_name': 'foo bar',
            },
            res,
        )

    @defer.inlineCallbacks
    def test_GithubVerifyCode_v4_teams(self):
        auth = yield self.setup_github_auth_v4_teams()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.post = mock.Mock(
            side_effect=[
                {
                    'data': {
                        'viewer': {
                            'organizations': {
                                'edges': [{'node': {'login': 'hello'}}, {'node': {'login': 'grp'}}]
                            },
                            'login': 'bar',
                            'email': 'bar@foo',
                            'name': 'foo bar',
                        }
                    }
                },
                {
                    'data': {
                        'hello': {
                            'teams': {
                                'edges': [
                                    {'node': {'name': 'developers', 'slug': 'develpers'}},
                                    {'node': {'name': 'contributors', 'slug': 'contributors'}},
                                ]
                            }
                        },
                        'grp': {
                            'teams': {
                                'edges': [
                                    {'node': {'name': 'developers', 'slug': 'develpers'}},
                                    {'node': {'name': 'contributors', 'slug': 'contributors'}},
                                    {'node': {'name': 'committers', 'slug': 'committers'}},
                                    {
                                        'node': {
                                            'name': 'Team with spaces and caps',
                                            'slug': 'team-with-spaces-and-caps',
                                        }
                                    },
                                ]
                            }
                        },
                    }
                },
            ]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'email': 'bar@foo',
                'username': 'bar',
                'groups': [
                    'hello',
                    'grp',
                    'grp/Team with spaces and caps',
                    'grp/committers',
                    'grp/contributors',
                    'grp/developers',
                    'grp/develpers',
                    'grp/team-with-spaces-and-caps',
                    'hello/contributors',
                    'hello/developers',
                    'hello/develpers',
                ],
                'full_name': 'foo bar',
            },
            res,
        )

    def test_GitHubAuthBadApiVersion(self):
        for bad_api_version in (2, 5, 'a'):
            with self.assertRaisesConfigError('GitHubAuth apiVersion must be 3 or 4 not '):
                oauth2.GitHubAuth("ghclientID", "clientSECRET", apiVersion=bad_api_version)

    def test_GitHubAuthRaiseErrorWithApiV3AndGetTeamMembership(self):
        with self.assertRaisesConfigError(
            'Retrieving team membership information using '
            'GitHubAuth is only possible using GitHub api v4.'
        ):
            oauth2.GitHubAuth("ghclientID", "clientSECRET", apiVersion=3, getTeamsMembership=True)

    @defer.inlineCallbacks
    def test_GitlabVerifyCode(self):
        auth = yield self.setup_gitlab_auth()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.get = mock.Mock(
            side_effect=[
                {  # /user
                    "name": "Foo Bar",
                    "username": "fbar",
                    "id": 5,
                    "avatar_url": "https://avatar/fbar.png",
                    "email": "foo@bar",
                    "twitter": "fb",
                },
                [  # /groups
                    {"id": 10, "name": "Hello", "path": "hello"},
                    {"id": 20, "name": "Group", "path": "grp"},
                ],
            ]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                "full_name": "Foo Bar",
                "username": "fbar",
                "email": "foo@bar",
                "avatar_url": "https://avatar/fbar.png",
                "groups": ["hello", "grp"],
            },
            res,
        )

    @defer.inlineCallbacks
    def test_BitbucketVerifyCode(self):
        auth = yield self.setup_bitbucket_auth()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.get = mock.Mock(
            side_effect=[
                {"username": 'bar', "display_name": 'foo bar'},  # /user
                {
                    "values": [
                        {'email': 'buzz@bar', 'is_primary': False},
                        {'email': 'bar@foo', 'is_primary': True},
                    ]
                },  # /user/emails
                {"values": [{'slug': 'hello'}, {'slug': 'grp'}]},  # /workspaces?role=member
            ]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'email': 'bar@foo',
                'username': 'bar',
                "groups": ["hello", "grp"],
                'full_name': 'foo bar',
            },
            res,
        )

    @defer.inlineCallbacks
    def test_loginResource(self):
        auth = yield self.setup_github_auth()

        class fakeAuth:
            homeUri = "://me"
            getLoginURL = mock.Mock(side_effect=lambda x: defer.succeed("://"))
            verifyCode = mock.Mock(side_effect=lambda code: defer.succeed({"username": "bar"}))
            acceptToken = mock.Mock(side_effect=lambda token: defer.succeed({"username": "bar"}))
            userInfoProvider = None

        rsrc = auth.getLoginResource()
        rsrc.auth = fakeAuth()
        res = yield self.render_resource(rsrc, b'/')
        rsrc.auth.getLoginURL.assert_called_once_with(None)
        rsrc.auth.verifyCode.assert_not_called()
        self.assertEqual(res, {'redirected': b'://'})
        rsrc.auth.getLoginURL.reset_mock()
        rsrc.auth.verifyCode.reset_mock()
        res = yield self.render_resource(rsrc, b'/?code=code!')
        rsrc.auth.getLoginURL.assert_not_called()
        rsrc.auth.verifyCode.assert_called_once_with(b"code!")
        self.assertEqual(self.master.session.user_info, {'username': 'bar'})
        self.assertEqual(res, {'redirected': b'://me'})
        # token not supported anymore
        res = yield self.render_resource(rsrc, b'/?token=token!')
        rsrc.auth.getLoginURL.assert_called_once()

    @defer.inlineCallbacks
    def test_getConfig_github(self):
        auth = yield self.setup_github_auth()
        self.assertEqual(
            auth.getConfigDict(),
            {'fa_icon': 'fa-github', 'autologin': False, 'name': 'GitHub', 'oauth2': True},
        )

    @defer.inlineCallbacks
    def test_getConfig_google(self):
        auth = yield self.setup_google_auth()
        self.assertEqual(
            auth.getConfigDict(),
            {'fa_icon': 'fa-google-plus', 'autologin': False, 'name': 'Google', 'oauth2': True},
        )

    @defer.inlineCallbacks
    def test_getConfig_gitlab(self):
        auth = yield self.setup_gitlab_auth()
        self.assertEqual(
            auth.getConfigDict(),
            {'fa_icon': 'fa-git', 'autologin': False, 'name': 'GitLab', 'oauth2': True},
        )

    @defer.inlineCallbacks
    def test_getConfig_bitbucket(self):
        auth = yield self.setup_bitbucket_auth()
        self.assertEqual(
            auth.getConfigDict(),
            {'fa_icon': 'fa-bitbucket', 'autologin': False, 'name': 'Bitbucket', 'oauth2': True},
        )


class TestKeyCloakAuth(TestReactorMixin, www.WwwTestMixin, ConfigErrorsMixin, unittest.TestCase):
    def setUp(self):
        self.setup_test_reactor()
        if requests is None:
            raise unittest.SkipTest("Need to install requests to test oauth2")

        self.patch(requests, 'request', mock.Mock(spec=requests.request))
        self.patch(requests, 'post', mock.Mock(spec=requests.post))
        self.patch(requests, 'get', mock.Mock(spec=requests.get))

    @defer.inlineCallbacks
    def setup_keycloak_auth(self):
        auth = oauth2.KeyCloakAuth("instance_uri", "realm", "client_id", "client_secret")
        master = yield self.make_master(url='http://localhost:5000/', auth=auth)
        auth.reconfigAuth(master, master.config)
        return auth

    @defer.inlineCallbacks
    def test_get_key_cloak_verify_code(self):
        auth = yield self.setup_keycloak_auth()

        res = yield auth.getLoginURL('http://redir')
        exp = (
            "instance_uri/realms/realm/protocol/openid-connect/auth?client_id=client_id&"
            "redirect_uri=http%3A%2F%2Flocalhost%3A5000%2Fauth%2Flogin&response_type=code&"
            "scope=openid&"
            "state=redirect%3Dhttp%253A%252F%252Fredir"
        )
        self.assertEqual(res, exp)
        res = yield auth.getLoginURL(None)
        exp = (
            "instance_uri/realms/realm/protocol/openid-connect/auth?client_id=client_id&"
            "redirect_uri=http%3A%2F%2Flocalhost%3A5000%2Fauth%2Flogin&response_type=code&"
            "scope=openid"
        )
        self.assertEqual(res, exp)

    @defer.inlineCallbacks
    def test_key_cloak_verify_code(self):
        auth = yield self.setup_keycloak_auth()

        requests.get.side_effect = []
        requests.post.side_effect = [FakeResponse({"access_token": 'TOK3N'})]
        auth.get = mock.Mock(
            side_effect=[
                {
                    "name": 'foo bar',
                    "preferred_username": 'bar',
                    "email": 'bar@foo',
                    "picture": 'http://pic',
                    "groups": ['group1', 'group2'],
                }
            ]
        )
        res = yield auth.verifyCode("code!")
        self.assertEqual(
            {
                'avatar_url': 'http://pic',
                'email': 'bar@foo',
                'full_name': 'foo bar',
                'username': 'bar',
                'groups': ["group1", "group2"],
            },
            res,
        )


# unit tests are not very useful to write new oauth support
# so following is an e2e test, which opens a browser, and do the oauth
# negotiation. The browser window close in the end of the test

# in order to use this tests, you need to create Github/Google ClientID (see doc on how to do it)
# point OAUTHCONF environment variable to a file with following params:
#  {
#  "GitHubAuth": {
#     "CLIENTID": "XX
#     "CLIENTSECRET": "XX"
#  },
#  "GoogleAuth": {
#     "CLIENTID": "XX",
#     "CLIENTSECRET": "XX"
#  }
#  "GitLabAuth": {
#     "INSTANCEURI": "XX",
#     "CLIENTID": "XX",
#     "CLIENTSECRET": "XX"
#  }
#  "KeyCloakAuth": {
#     "INSTANCEURI": "XX",
#     "REALM": "XX",
#     "CLIENTID": "XX",
#     "CLIENTSECRET": "XX"
#  }
#  }


class OAuth2AuthGitHubE2E(TestReactorMixin, www.WwwTestMixin, unittest.TestCase):
    authClass = "GitHubAuth"
    timeout = 60
    ssl_verify = True

    def _instantiateAuth(self, cls, config):
        return cls(config["CLIENTID"], config["CLIENTSECRET"])

    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()

        if requests is None:
            raise unittest.SkipTest("Need to install requests to test oauth2")

        if "OAUTHCONF" not in os.environ:
            raise unittest.SkipTest(
                "Need to pass OAUTHCONF path to json file via environ to run this e2e test"
            )

        with open(os.environ['OAUTHCONF'], encoding='utf-8') as f:
            jsonData = f.read()
        config = json.loads(jsonData).get(self.authClass, None)
        if config is None:
            raise unittest.SkipTest(f"{self.authClass} is not in OAUTHCONF file")
        from buildbot.www import oauth2

        self.auth = self._instantiateAuth(getattr(oauth2, self.authClass), config)

        # 5000 has to be hardcoded, has oauth clientids are bound to a fully
        # classified web site
        master = yield self.make_master(url='http://localhost:5000/', auth=self.auth)
        self.auth.reconfigAuth(master, master.config)

    def tearDown(self):
        from twisted.internet.tcp import Server

        # browsers has the bad habit on not closing the persistent
        # connections, so we need to hack them away to make trial happy
        f = failure.Failure(Exception("test end"))
        for reader in reactor.getReaders():
            if isinstance(reader, Server):
                reader.connectionLost(f)

    @defer.inlineCallbacks
    def test_E2E(self):
        d = defer.Deferred()
        twisted.web.http._logDateTimeUsers = 1

        class HomePage(Resource):
            isLeaf = True

            def render_GET(self, request):
                info = request.getSession().user_info
                reactor.callLater(0, d.callback, info)
                return (
                    b"<html><script>setTimeout(close,1000)</script><body>WORKED: "
                    + str(info).encode('utf-8')
                    + b"</body></html>"
                )

        class MySite(SiteWithClose):
            def makeSession(self):
                uid = self._mkuid()
                session = self.sessions[uid] = self.sessionFactory(self, uid)
                session.updateSession = mock.Mock()
                return session

        root = Resource()
        root.putChild(b"", HomePage())
        auth = Resource()
        root.putChild(b'auth', auth)
        auth.putChild(b'login', self.auth.getLoginResource())
        site = MySite(root)
        listener = reactor.listenTCP(5000, site)

        def thd():
            self.assertTrue(
                webbrowser.open('http://localhost:5000/auth/login'), "Could not open web browser"
            )

        with warnings.catch_warnings():
            if not self.ssl_verify:
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            twistedDeferToThread(thd)
            res = yield d
        yield listener.stopListening()
        yield site.stopFactory()
        yield site.close_connections()

        self.assertIn("full_name", res)
        self.assertIn("email", res)
        self.assertIn("username", res)


class OAuth2AuthGoogleE2E(OAuth2AuthGitHubE2E):
    authClass = "GoogleAuth"


class OAuth2AuthGitLabE2E(OAuth2AuthGitHubE2E):
    authClass = "GitLabAuth"

    def _instantiateAuth(self, cls, config):
        return cls(config["INSTANCEURI"], config["CLIENTID"], config["CLIENTSECRET"])


class OAuth2AuthKeyCloakE2E(OAuth2AuthGitHubE2E):
    authClass = "KeyCloakAuth"
    ssl_verify = False

    def _instantiateAuth(self, cls, config):
        return cls(
            config["INSTANCEURI"],
            config["REALM"],
            config["CLIENTID"],
            config["CLIENTSECRET"],
            ssl_verify=False,  # self-hosted instance uses self-signed certificate
        )
