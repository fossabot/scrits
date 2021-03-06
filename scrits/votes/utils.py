# -*- coding: utf-8 -*-
# based on secretballot
import django
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Manager


def limit_total_votes(num):
    from .models import Vote

    def total_vote_limiter(request, content_type, object_id, vote):
        return Vote.objects.filter(content_type=content_type,
                                   token=request.secretballot_token).count() < num
    return total_vote_limiter


def enable_voting_on(
        cls, manager_name='objects',
        votes_name='votes', upvotes_name='total_upvotes',
        downvotes_name='total_downvotes', total_name='vote_total',
        add_vote_name='add_vote', remove_vote_name='remove_vote',
        base_manager=None):

    from django.contrib.contenttypes.models import ContentType
    from django.contrib.contenttypes.fields import GenericRelation
    from .models import Vote

    VOTE_TABLE = Vote._meta.db_table

    def add_vote(self, token, vote):
        voteobj, created = getattr(self, votes_name).get_or_create(
            token=token,
            defaults={
                'vote': vote,
                'content_object': self
            })
        if not created:
            voteobj.vote = vote
            voteobj.save()

    def remove_vote(self, token):
        getattr(self, votes_name).filter(token=token).delete()

    # gets added to the class as a property, not under this name
    def get_total(self):
        return getattr(self, upvotes_name) - getattr(self, downvotes_name)

    if base_manager is None:
        if hasattr(cls, manager_name):
            base_manager = getattr(cls, manager_name).__class__
        else:
            base_manager = Manager

    class VotableManager(base_manager):

        use_for_related_fields = True

        def get_queryset(self):
            db_table = self.model._meta.db_table
            pk_name = self.model._meta.pk.attname

            try:
                content_type = ContentType.objects.get_for_model(self.model).id
            except:
                content_type = None

            downvote_query = '(SELECT COUNT(*) from %s WHERE vote=-1 AND object_id=%s.%s AND content_type_id=%s)' % (VOTE_TABLE, db_table, pk_name, content_type)
            upvote_query = '(SELECT COUNT(*) from %s WHERE vote=1 AND object_id=%s.%s AND content_type_id=%s)' % (VOTE_TABLE, db_table, pk_name, content_type)

            return super(VotableManager, self).get_queryset().extra(
                select={upvotes_name: upvote_query,
                        downvotes_name: downvote_query})

        def from_token(self, token):
            db_table = self.model._meta.db_table
            pk_name = self.model._meta.pk.attname
            content_type = ContentType.objects.get_for_model(self.model).id
            query = '(SELECT vote from %s WHERE token=%%s AND object_id=%s.%s AND content_type_id=%s)' % (
                VOTE_TABLE, db_table, pk_name, content_type)

            return self.get_queryset().extra(select={'user_vote': query}, select_params=(token,))

        def from_request(self, request):
            if not hasattr(request, 'secretballot_token'):
                raise ImproperlyConfigured('To use voting a votingMiddleware must '
                                           'be installed. (see voting/middleware.py)')

            return self.from_token(request.secretballot_token)

    if django.VERSION < (1, 10):
        cls.add_to_class('_default_manager', VotableManager())
        cls.add_to_class(manager_name, VotableManager())
    else:
        # this is a hack but by setting a distinct name and appending
        # to local_managers the manager seems to be selected as the default
        vm = VotableManager()
        vm.name = manager_name + 'votable'
        cls._meta.local_managers.append(vm)
        cls._meta.default_manager_name = manager_name + 'votable'
        cls.add_to_class(manager_name, vm)

    cls.add_to_class(votes_name, GenericRelation(Vote))
    cls.add_to_class(total_name, property(get_total))
    cls.add_to_class(add_vote_name, add_vote)
    cls.add_to_class(remove_vote_name, remove_vote)

    setattr(cls, '_voting_enabled', True)
