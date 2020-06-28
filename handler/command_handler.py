# -*- coding: utf-8 -*-
# Copyright © Thomm.o 2020
#
# This file is part of Hikari Command Handler.
#
# Hikari Command Handler is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Hikari Command Handler is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Hikari Command Handler. If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

import typing
import functools
import collections
import asyncio

import hikari
from hikari.events import message

from handler import commands
from handler import context
from handler import errors
from handler import stringview

if typing.TYPE_CHECKING:
    from hikari.models import messages


async def _return_prefix(
    _, __, *, prefixes: typing.Union[str, typing.List[str], typing.Tuple[str]]
) -> typing.Union[str, typing.List[str], typing.Tuple[str]]:
    return prefixes


class BotWithHandler(hikari.Bot):
    """
    A subclassed implementation of :class:`hikari.impl.bot.BotAppImpl` which contains a command handler.
    This should be instantiated instead of the superclass if you want to be able to use 
    the command handler implementation provided.

    Args:
        prefix (:obj:`str`): The bot's command prefix.
        ignore_bots (:obj:`bool`): Whether or not the bot should ignore its commands when invoked by other bots. Defaults to ``True``.
        owner_ids (List[ :obj:`int` ]): IDs that the bot should treat as owning the bot.
        **kwargs: Other parameters passed to the :class:`hikari.impl.bot.BotAppImpl` constructor.
    """

    def __init__(
        self,
        *,
        prefix: typing.Union[
            str,
            typing.Iterable[str],
            typing.Callable[
                [BotWithHandler, messages.Message],
                typing.Coroutine[None, typing.Any, str],
            ],
        ],
        ignore_bots: bool = True,
        owner_ids: typing.Iterable[int] = (),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.event_dispatcher.subscribe(message.MessageCreateEvent, self.handle)

        if isinstance(prefix, str):
            self.get_prefix = functools.partial(_return_prefix, prefixes=[prefix])
        elif isinstance(prefix, collections.abc.Iterable):
            self.get_prefix = functools.partial(_return_prefix, prefixes=prefix)
        else:
            self.get_prefix = prefix

        self.ignore_bots: bool = ignore_bots
        self.owner_ids: typing.Iterable[int] = owner_ids
        self.commands: typing.MutableMapping[
            str, typing.Union[commands.Command, commands.Group]
        ] = {}

    async def _default_command_error(self, event: errors.CommandErrorEvent) -> None:
        raise event.error

    async def fetch_owner_ids(self) -> None:
        """
        Fetches the IDs of the bot's owner(s) from the API and stores them in
        :attr:`.command_handler.BotWithHandler.owner_ids`

        Returns:
            ``None``
        """
        # TODO - add way to flush the owner_id cache
        application = await self.rest.fetch_application()
        self.owner_ids = []
        if application.owner is not None:
            self.owner_ids.append(application.owner.id)
        if application.team is not None:
            self.owner_ids.extend([member_id for member_id in application.team.members])

    def command(
        self, *, allow_extra_arguments: bool = True, name: typing.Optional[str] = None
    ) -> typing.Callable:
        """
        A decorator that registers a callable as a command for the handler.

        Args:
            allow_extra_arguments (:obj:`bool`): Whether or not the handler should raise an error if the command is run
                with more arguments than it requires. Defaults to True.
            name (:obj:`str`): Optional name of the command. Defaults to the name of the function if not specified.

        Example:

            .. code-block:: python

                bot = handler.Bot(token="token_here", prefix="!")

                @bot.command()
                async def ping(ctx):
                    await ctx.reply("Pong!")

        See Also:
            :meth:`.command_handler.BotWithHandler.add_command`
        """
        registered_commands = self.commands

        def decorate(func: typing.Callable):
            nonlocal registered_commands
            nonlocal allow_extra_arguments
            nonlocal name
            name = func.__name__ if name is None else name
            if not registered_commands.get(name):
                registered_commands[name] = commands.Command(
                    func, allow_extra_arguments, name
                )
                return registered_commands[name]

        return decorate

    def group(
        self, *, allow_extra_arguments: bool = True, name: typing.Optional[str] = None
    ) -> typing.Callable:
        """
        A decorator that registers a callable as a command group for the handler.

        Args:
            allow_extra_arguments (:obj:`bool`): Whether or not the handler should raise an error if the command is run
                with more arguments than it requires. Defaults to True.
            name (:obj:`str`): Optional name of the command. Defaults to the name of the function if not specified.

        Example:

            .. code-block:: python

                bot = handler.Bot(token="token_here", prefix="!")

                @bot.group()
                async def foo(ctx):
                    await ctx.reply("Bar")

        See Also:
            :meth:`.commands.Group.command` for how to add subcommands to a group.
        """
        registered_commands = self.commands

        def decorate(func: typing.Callable):
            nonlocal registered_commands
            nonlocal allow_extra_arguments
            nonlocal name
            name = func.__name__ if name is None else name
            if not registered_commands.get(name):
                registered_commands[name] = commands.Group(
                    func, allow_extra_arguments, name
                )
                return registered_commands.get(name)

        return decorate

    def add_command(
        self,
        func: typing.Callable,
        *,
        allow_extra_arguments=True,
        name: typing.Optional[str] = None,
    ) -> None:
        """
        Adds a command to the bot. Similar to the ``command`` decorator.

        Args:
            func (:obj:`typing.Callable`): The function to add as a command.
            allow_extra_arguments (:obj:`bool`): Whether or not the handler should raise an error if the command is run
                with more arguments than it requires. Defaults to True.
            name (:obj:`str`): Optional name of the command. Defaults to the name of the function if not specified.

        Returns:
            ``None``

        Example:

            .. code-block:: python

                bot = handler.Bot(token="token_here", prefix="!")

                async def ping(ctx):
                    await ctx.reply("Pong!")

                bot.add_command(ping)

        See Also:
            :meth:`.command_handler.BotWithHandler.command`
        """
        name = func.__name__ if name is None else name
        if not self.commands.get(name):
            self.commands[name] = commands.Command(func, allow_extra_arguments, name)

    def add_group(
        self,
        func: typing.Callable,
        *,
        allow_extra_arguments=True,
        name: typing.Optional[str] = None,
    ) -> None:
        """
        Adds a command group to the bot. Similar to the ``group`` decorator.

        Args:
            func (:obj:`typing.Callable`): The function to add as a command group.
            allow_extra_arguments (:obj:`bool`): Whether or not the handler should raise an error if the command is run
                with more arguments than it requires. Defaults to True.
            name (:obj:`str`): Optional name of the command group. Defaults to the name of the function if not specified.

        Returns:
            ``None``

        See Also:
            :meth:`.command_handler.BotWithHandler.group`
            :meth:`.command_handler.BotWithHandler.add_command`
        """
        name = func.__name__ if name is None else name
        if not self.commands.get(name):
            self.commands[name] = commands.Group(func, allow_extra_arguments, name)

    def get_command(self, name: str) -> typing.Optional[commands.Command]:
        """
        Get a command object from it's registered name.

        Args:
            name (:obj:`str`): The name of the command to get the object for.

        Returns:
            Optional[ :obj:`.commands.Command` ] command object registered to that name.
        """
        return self.commands.get(name)

    def remove_command(self, name: str) -> typing.Optional[str]:
        """
        Remove a command from the bot and return its name or ``None`` if no command was removed.

        Args:
            name (:obj:`str`): The name of the command to remove.

        Returns:
            Optional[ :obj:`str` ] name of the command that was removed.
        """
        command = self.commands.pop(name)
        return command.name if command is not None else None

    def resolve_arguments(self, message: messages.Message) -> typing.List[str]:
        """
        Resolves the arguments that a command was invoked with from the message containing the invocation.

        Args:
            message (:obj:`hikari.models.messages.Message`): The message to resolve the arguments for.

        Returns:
            List[ :obj:`str` ] List of the arguments the command was invoked with.

        Note:
            The first item in the list will always contain the prefix+command string which can
            be used to validate if the message was intended to invoke a command and if the command
            they attempted to invoke is actually valid.
        """
        string_view = stringview.StringView(message.content)
        return string_view.deconstruct_str()

    async def _evaluate_checks(
        self, command: commands.Command, context: context.Context
    ):
        for check in command.checks:
            try:
                check_pass = await check(context)
                if not check_pass:
                    raise errors.CheckFailure(
                        f"Check {check.__name__} failed for command {context.invoked_with}"
                    )
            except errors.OnlyInGuild as e:
                self.event_dispatcher.dispatch(
                    errors.CommandErrorEvent(e, context.message)
                )
                return False
            except errors.OnlyInDM as e:
                self.event_dispatcher.dispatch(
                    errors.CommandErrorEvent(e, context.message)
                )
                return False
            except errors.NotOwner as e:
                self.event_dispatcher.dispatch(
                    errors.CommandErrorEvent(e, context.message)
                )
                return False
            except errors.CheckFailure as e:
                self.event_dispatcher.dispatch(
                    errors.CommandErrorEvent(e, context.message)
                )
                return False
        return True

    async def _invoke_command(
        self,
        command: commands.Command,
        context: context.Context,
        args: typing.List[str],
    ) -> None:
        if not await self._evaluate_checks(command, context):
            return

        if not command._has_max_args and len(args) >= command._min_args:
            await command(context, *args)

        elif len(args) < command._max_args:
            self.event_dispatcher.dispatch(
                errors.CommandErrorEvent(
                    errors.NotEnoughArguments(context.invoked_with), context.message
                )
            )
            return

        elif len(args) > command._max_args and not command.allow_extra_arguments:
            self.event_dispatcher.dispatch(
                errors.CommandErrorEvent(
                    errors.TooManyArguments(context.invoked_with), context.message
                )
            )
            return

        elif command._max_args == 0:
            await command(context)

        else:
            await command(context, *args[: command._max_args + 1])

    async def handle(self, event: message.MessageCreateEvent) -> None:
        """
        The message listener that deals with validating the invocation messages. If invocation message
        is valid then it will invoke the relevant command.

        Args:
            event (:obj:`hikari.events.message.MessageCreateEvent`): The message create event containing a possible command invocation.

        Returns:
            ``None``
        """
        if self.ignore_bots and event.message.author.is_bot:
            return

        if not event.message.content:
            return

        args = self.resolve_arguments(event.message)

        if asyncio.iscoroutine(self.get_prefix):
            prefixes = await self.get_prefix(self, event.message)
        else:
            prefixes = self.get_prefix(self, event.message)

        if isinstance(prefixes, str):
            prefixes = [prefixes]

        prefix = None
        for p in prefixes:
            if args[0].startswith(p):
                prefix = p
                break

        if prefix is None:
            return

        invoked_with = args[0].replace(prefix, "")
        if invoked_with not in self.commands:
            self.event_dispatcher.dispatch(
                errors.CommandErrorEvent(
                    errors.CommandNotFound(invoked_with), event.message
                )
            )
            return

        invoked_command = self.commands[invoked_with]
        if isinstance(invoked_command, commands.Command):
            new_args = args[1:]
        if isinstance(invoked_command, commands.Group):
            invoked_command, new_args = invoked_command.resolve_subcommand(args)

        command_context = context.Context(
            self, event.message, prefix, invoked_with, invoked_command
        )
        await self._invoke_command(invoked_command, command_context, new_args)

    def run(self) -> None:
        if errors.CommandErrorEvent not in self.event_dispatcher._listeners:
            self.event_dispatcher.subscribe(
                errors.CommandErrorEvent, self._default_command_error
            )
        super().run()
