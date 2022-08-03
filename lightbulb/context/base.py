# -*- coding: utf-8 -*-
# Copyright © tandemdude 2020-present
#
# This file is part of Lightbulb.
#
# Lightbulb is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Lightbulb is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Lightbulb. If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

__all__ = ["Context", "OptionsProxy", "ResponseProxy"]

import abc
import asyncio
import datetime
import typing as t

import hikari

if t.TYPE_CHECKING:
    from lightbulb import app as app_
    from lightbulb import commands


class OptionsProxy:
    """
    Proxy for the options that the command was invoked with allowing access using
    dot notation as well as dictionary lookup.

    Args:
        options (Dict[:obj:`str`, Any]): Options to act as a proxy for.
    """

    def __init__(self, options: t.Dict[str, t.Any]) -> None:
        self._options = options

    def __getattr__(self, item: str) -> t.Any:
        return self._options.get(item)

    def __getitem__(self, item: str) -> t.Any:
        return self._options.get(item)


class ResponseProxy:
    """
    Proxy for context responses. Allows fetching of the message created from the response
    lazily instead of a follow-up request being made immediately.
    """

    __slots__ = ("_message", "_context", "_delete_after_task")

    def __init__(
        self,
        context: Context,
        message: t.Optional[hikari.Message] = None,
    ) -> None:

        # If the proxy has a message, it's a followup, otherwise initial response
        self._message: t.Optional[hikari.Message] = message
        self._context: Context = context
        self._delete_after_task: t.Optional[asyncio.Task[None]] = None

    def __await__(self) -> t.Generator[t.Any, None, hikari.Message]:
        return self.retrieve_message().__await__()

    async def _do_delete_after(self, delay: float) -> None:
        """Delete the response after the specified delay.

        This should not be called manually,
        and instead should be triggered by the ``delete_after`` method of this class.
        """
        await asyncio.sleep(delay)
        await self.delete()

    def delete_after(self, delay: t.Union[int, float, datetime.timedelta]) -> None:
        """Delete the response after the specified delay.

        Returns:
            ``None``
        """
        if self._delete_after_task is not None:
            raise RuntimeError("A delete_after task is already running.")

        if isinstance(delay, datetime.timedelta):
            delay = delay.total_seconds()
        self._delete_after_task = asyncio.create_task(self._do_delete_after(delay))

    async def retrieve_message(self) -> hikari.Message:
        """
        Fetches and/or returns the created message from the context response.

        Returns:
            :obj:`~hikari.messages.Message`: The response's created message.

        Note:
            This object is awaitable (since version `2.2.2`), hence the following is also valid.

            .. code-block:: python

                # Where 'response' is an instance of ResponseProxy

                # Calling this method
                message = await response.retrieve_message()
                # Awaiting the object itself
                message = await response
        """
        if self._message is not None:
            return self._message
        message = await self._context.interaction.fetch_initial_response()
        return message

    async def edit(
        self,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        *,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        replace_attachments: bool = False,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> hikari.Message:
        """
        Edits the message that this object is proxying.

        Returns:
            :obj:`~hikari.messages.Message`: New message after edit.
        """
        if self._message:
            return await self._context.interaction.edit_message(
                self._message,
                content,
                component=component,
                components=components,
                attachment=attachment,
                attachments=attachments,
                embed=embed,
                embeds=embeds,
                replace_attachments=replace_attachments,
                mentions_everyone=mentions_everyone,
                user_mentions=user_mentions,
                role_mentions=role_mentions,
            )

        return await self._context.interaction.edit_initial_response(
            content,
            component=component,
            components=components,
            attachment=attachment,
            attachments=attachments,
            embed=embed,
            embeds=embeds,
            replace_attachments=replace_attachments,
            mentions_everyone=mentions_everyone,
            user_mentions=user_mentions,
            role_mentions=role_mentions,
        )

    async def delete(self) -> None:
        """
        Deletes the message that this object is proxying.

        Returns:
            ``None``
        """
        if self._message:
            await self._context.interaction.delete_message(self._message)

        await self._context.interaction.delete_initial_response()


class Context(abc.ABC):
    """
    Abstract base class for all context types.

    Args:
        app (:obj:`~.app.BotApp`): The ``BotApp`` instance that the context is linked to.
    """

    __slots__ = ("_app", "_responses", "_responded", "_deferred", "_invoked", "_event", "_interaction", "_command")

    def __init__(self, app: app_.BotApp, event: hikari.InteractionCreateEvent, command: commands.base.Command):
        self._app = app
        self._responses: t.List[ResponseProxy] = []
        self._responded: bool = False
        self._deferred: bool = False
        self._invoked: t.Optional[commands.base.Command] = None
        self._event = event
        assert isinstance(event.interaction, hikari.CommandInteraction)
        self._interaction: hikari.CommandInteraction = event.interaction
        self._command = command

    async def _maybe_defer(self) -> None:
        if (self._invoked or self._command).auto_defer:
            await self.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    @property
    def deferred(self) -> bool:
        """Whether or not the response from this context is currently deferred."""
        return self._deferred

    @property
    def responses(self) -> t.List[ResponseProxy]:
        """List of all previous responses sent for this context."""
        return self._responses

    @property
    def previous_response(self) -> t.Optional[ResponseProxy]:
        """The last response sent for this context."""
        return self._responses[-1] if self._responses else None

    @property
    def interaction(self) -> hikari.CommandInteraction:
        """The interaction that triggered this context."""
        return self._interaction

    @property
    def resolved(self) -> t.Optional[hikari.ResolvedOptionData]:
        """The resolved option data for this context."""
        return self._interaction.resolved

    @property
    def app(self) -> app_.BotApp:
        """The ``BotApp`` instance the context is linked to."""
        return self._app

    @property
    def bot(self) -> app_.BotApp:
        """Alias for :obj:`~Context.app`"""
        return self.app

    @property
    def event(self) -> hikari.InteractionCreateEvent:
        """The event for the context."""
        return self._event

    @property
    def raw_options(self) -> t.Dict[str, t.Any]:
        """Dictionary of :obj:`str` option name to option value that the user invoked the command with."""
        return {}

    @property
    def options(self) -> OptionsProxy:
        """:obj:`~OptionsProxy` wrapping the options that the user invoked the command with."""
        return OptionsProxy(self.raw_options)

    @property
    def channel_id(self) -> hikari.Snowflakeish:
        """The channel ID for the context."""
        return self._interaction.channel_id

    @property
    def guild_id(self) -> t.Optional[hikari.Snowflakeish]:
        """The guild ID for the context."""
        return self._interaction.guild_id

    @property
    def member(self) -> t.Optional[hikari.Member]:
        """The member for the context."""
        return self._interaction.member

    @property
    def author(self) -> hikari.User:
        """The author for the context."""
        return self._interaction.user

    @property
    def user(self) -> hikari.User:
        """The user for the context. Alias for :obj:`~Context.author`."""
        return self.author

    @property
    def invoked_with(self) -> str:
        return self._command.name

    @property
    def command_id(self) -> hikari.Snowflake:
        return self._interaction.command_id

    @property
    @abc.abstractmethod
    def command(self) -> commands.base.Command:
        """
        The root command object that the context is for.

        See Also:
            :obj:`~Context.invoked`
        """
        ...

    @property
    def invoked(self) -> t.Optional[commands.base.Command]:
        """
        The command or subcommand that was invoked in this context.

        .. versionadded:: 2.1.0
        """
        return self._invoked

    def _create_response(self, message: t.Optional[hikari.Message] = None) -> ResponseProxy:
        """Create a new response and add it to the list of tracked responses."""
        response = ResponseProxy(self, message)
        self._responses.append(response)
        return response

    def get_channel(self) -> t.Optional[t.Union[hikari.GuildChannel, hikari.Snowflake]]:
        """The channel object for the context's channel ID."""
        return self._app.cache.get_guild_channel(self.channel_id)

    def get_guild(self) -> t.Optional[hikari.Guild]:
        """The guild object for the context's guild ID."""
        if self.guild_id is None:
            return None
        return self.app.cache.get_guild(self.guild_id)

    async def invoke(self) -> None:
        """
        Invokes the context's command under the current context.

        Returns:
            ``None``
        """
        if self.command is None:
            raise TypeError("This context cannot be invoked - no command was resolved.")
        await self._maybe_defer()
        await self.command.invoke(self)

    @t.overload
    async def respond(
        self,
        response_type: hikari.ResponseType,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, datetime.timedelta, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        flags: hikari.UndefinedOr[t.Union[int, hikari.MessageFlag]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> ResponseProxy:
        ...

    @t.overload
    async def respond(
        self,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, datetime.timedelta, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        flags: hikari.UndefinedOr[t.Union[int, hikari.MessageFlag]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> ResponseProxy:
        ...

    async def respond(
        self, *args: t.Any, delete_after: t.Union[int, float, datetime.timedelta, None] = None, **kwargs: t.Any
    ) -> ResponseProxy:
        """
        Create a response to this context.
        """
        if args and isinstance(args[0], hikari.ResponseType):
            response_type = args[0]
            args = args[1:]
        else:
            response_type = hikari.ResponseType.MESSAGE_CREATE

        if self._responded:
            message = await self.interaction.execute(*args, **kwargs)
            response = self._create_response(message)
        else:
            await self.interaction.create_initial_response(response_type, *args, **kwargs)  # type: ignore [arg-type]
            response = self._create_response()
            self._responded = True

        if delete_after:
            response.delete_after(delete_after)
        return response

    async def edit_last_response(
        self,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        *,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        replace_attachments: bool = False,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]],
    ) -> hikari.Message:
        """
        Edit the most recently sent response. Shortcut for :obj:`hikari.messages.Message.edit`.

        Returns:
            :obj:`~hikari.messages.Message`: New message after edit.
        Raises:
            ``RuntimeError``: If no responses have been sent for this context yet.
        """
        if not self._responses:
            raise RuntimeError("No responses have been sent for this context yet.")

        return await self._responses[-1].edit(
            content,
            component=component,
            components=components,
            attachment=attachment,
            attachments=attachments,
            embed=embed,
            embeds=embeds,
            replace_attachments=replace_attachments,
            mentions_everyone=mentions_everyone,
            user_mentions=user_mentions,
            role_mentions=role_mentions,
        )

    async def delete_last_response(self) -> None:
        """
        Delete the most recently send response. Shortcut for :obj:`hikari.messages.Message.delete`.

        Returns:
            ``None``
        Raises:
            ``RuntimeError``: If no responses have been sent for this context yet.
        """
        if not self._responses:
            raise RuntimeError("No responses have been sent for this context yet.")

        await self._responses.pop().delete()
