# coding: utf-8


import re
import random
import hashlib
import datetime

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import Signal
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


SHA1_RE = re.compile('^[a-f0-9]{40}$')
ACTIVATED = u"ALREADY_ACTIVATED"

inactive_user_created = Signal(providing_args=["user", "extra_info"])
user_activated = Signal(providing_args=["user"])


class Page(models.Model):
    name = models.CharField(_("name"), max_length=255, unique=True, db_index=True)
    url = models.CharField(_("URL"), max_length=255, unique=True, db_index=True)
    title = models.CharField(_("title"), max_length=255, blank=True)
    content = models.TextField(_("content"), blank=True)
    template_name = models.CharField(_("template"), max_length=70, blank=True)
    registration_required = models.BooleanField(_("registration required"), default=False)

    class Meta:
        ordering = ('name',)

    def __repr__(self):
        return "<Page: %s url: %s>" % (self.name, self.url)

    def get_absolute_url(self):
        return self.url

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.url.replace("/", "-").strip("-")

        return super(Page, self).save(*args, **kwargs)


CONTACT_STATUS = (
    ("N", _("New")),
    ("O", _("Ongoing")),
    ("R", _("Resolved")),
    ("C", _("Closed")),
    ("I", _("Invalid")),
)


class Contact(models.Model):
    status = models.CharField(_("status"), max_length=1, choices=CONTACT_STATUS, default="N")
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"), max_length=255)
    phone = models.CharField(_("phone"), max_length=100, blank=True)
    message = models.TextField(_("message"))


def send_contact_mail(instance, created, **kwargs):
    if not created:
        return

    template = _(
        "Contact From: {instance.name} <{instance.email}>\n"
        "Phone: {instance.phone}\n"
        "Message:\n"
        "{instance.message}"
    )

    email = EmailMessage(
        subject=_("New Contact from %s") % (settings.PROJECT_NAME,),
        body=template.format(instance=instance),
        from_email=instance.email,
        to=[settings.PROJECT_CONTACT],
        headers={"Reply-To": instance.email},
    )

    email.send(fail_silently=True)


if settings.DEFAULT_TRANSACTIONAL_EMAIL.get("contact"):
    post_save.connect(send_contact_mail, Contact, dispatch_uid="quickstartup.contact")


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, is_active=True):
        if not email:
            raise ValueError('Users must have an email address')

        user = self.model(email=self.normalize_email(email), is_active=is_active)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password):
        user = self.create_user(email, password=password)
        user.is_superuser = True
        user.is_staff = True
        user.save(using=self._db)
        return user

    def _get_activation_key(self, email):
        salt = hashlib.sha1(str(random.random())).hexdigest()[:5]
        if isinstance(email, unicode):
            email = email.encode('utf-8')
        activation_key = hashlib.sha1(salt + email).hexdigest()
        return activation_key

    def create_inactive_user(self, email, password, extra_info=None):
        user = self.create_user(email=email, password=password, is_active=False)
        user.activation_key = self._get_activation_key(user.email)
        user.save()

        inactive_user_created.send(sender=user, extra_info=extra_info)

        return user

    def activate_user(self, activation_key):
        if SHA1_RE.search(activation_key):
            try:
                user = self.get(activation_key=activation_key)
            except self.model.DoesNotExist:
                return

            if user.activation_key_expired():
                return

            user.is_active = True
            user.activation_key = ACTIVATED
            user.save()

            user_activated.send(sender=user)

            return user


class User(AbstractBaseUser, PermissionsMixin):
    objects = UserManager()

    email = models.EmailField(_("email"), max_length=255, unique=True, db_index=True)
    created = models.DateTimeField(_("created"), default=timezone.now)
    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(_("staff"), default=False)
    activation_key = models.CharField(_('activation key'), max_length=40, db_index=True)

    USERNAME_FIELD = "email"

    def get_short_name(self):
        return self.email

    def get_username(self):
        return self.email

    def activation_key_expired(self):
        if self.activation_key == self.ACTIVATED:
            return True

        expiration_date = datetime.timedelta(days=settings.ACCOUNT_ACTIVATION_DAYS)
        if self.created + expiration_date <= timezone.now():
            return True

    activation_key_expired.boolean = True