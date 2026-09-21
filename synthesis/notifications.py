from datetime import timedelta

from django.utils import timezone

from .models import (
    ActivityReport,
    CollectionStatus,
    Notification,
    ReportVersion,
    User,
    UserRole,
    WeeklyCycle,
    WeeklyReport,
)


def deadline_label(deadline):
    return timezone.localtime(deadline).strftime("%d/%m/%Y às %H:%M")


def notify(user, *, kind: str, message: str, href: str, key: str) -> None:
    Notification.objects.get_or_create(
        user=user,
        dedupe_key=key,
        defaults={"kind": kind, "message": message[:300], "href": href},
    )


def notify_managers(*, kind: str, message: str, href: str, key: str) -> None:
    for manager in User.objects.filter(role=UserRole.MANAGER, active=True).iterator():
        notify(manager, kind=kind, message=message, href=href, key=key)


def clear_deadline_reminders(cycle: WeeklyCycle) -> None:
    Notification.objects.filter(kind="prazo", dedupe_key__startswith=f"deadline:{cycle.id}:").delete()


def activity_created(actor: User, report: ActivityReport) -> None:
    href = f"/relatos/{report.id}"
    reminder_key = f"deadline:{report.cycle_id}:"
    Notification.objects.filter(user=actor, kind="prazo", dedupe_key__startswith=reminder_key).delete()
    Notification.objects.filter(
        user=actor, dedupe_key__startswith=f"cycle:current:{report.cycle_id}:"
    ).delete()
    Notification.objects.filter(
        user__role__in=(UserRole.EDITOR, UserRole.ADMIN),
        kind="prazo",
        dedupe_key__startswith=reminder_key,
    ).delete()
    notify(
        actor, kind="conclusao", message=f'Relato "{report.title}" enviado com sucesso.',
        href=href, key=f"activity:created:{report.id}",
    )
    for editor in User.objects.filter(role__in=(UserRole.EDITOR, UserRole.ADMIN), active=True).iterator():
        notify(
            editor, kind="atividade", message=f'{actor.name} enviou o relato "{report.title}".',
            href=href, key=f"activity:received:{report.id}",
        )


def activity_updated(actor: User, report: ActivityReport) -> None:
    notify(
        actor, kind="conclusao", message=f'Alterações no relato "{report.title}" salvas.',
        href=f"/relatos/{report.id}",
        key=f"activity:updated:{report.id}:{report.updated_at.isoformat()}",
    )


def cycle_opened(actor: User, cycle: WeeklyCycle) -> None:
    suffix = f"{cycle.id}:{cycle.updated_at.isoformat()}"
    notify(
        actor, kind="conclusao", message=f'Ciclo "{cycle.label}" aberto com sucesso.',
        href="/ciclos", key=f"cycle:created:actor:{suffix}",
    )
    notify_managers(
        kind="ciclo",
        message=f'O ciclo "{cycle.label}" foi aberto. Envie seu relato até {deadline_label(cycle.deadline)}.',
        href="/relatos/novo", key=f"cycle:opened:{suffix}",
    )


def cycle_closed(actor: User, cycle: WeeklyCycle) -> None:
    clear_deadline_reminders(cycle)
    suffix = f"{cycle.id}:{cycle.updated_at.isoformat()}"
    notify(actor, kind="conclusao", message=f'Ciclo "{cycle.label}" encerrado.',
           href="/ciclos", key=f"cycle:closed:actor:{suffix}")
    notify_managers(kind="ciclo", message=f'O ciclo "{cycle.label}" foi encerrado.',
                    href="/relatos", key=f"cycle:closed:{suffix}")


def cycle_deadline_updated(actor: User, cycle: WeeklyCycle) -> None:
    clear_deadline_reminders(cycle)
    suffix = f"{cycle.id}:{cycle.updated_at.isoformat()}"
    notify_managers(
        kind="prazo",
        message=f'O prazo do ciclo "{cycle.label}" mudou para {deadline_label(cycle.deadline)}.',
        href="/relatos/novo", key=f"cycle:deadline:{suffix}",
    )
    notify(actor, kind="conclusao", message=f'Prazo do ciclo "{cycle.label}" atualizado.',
           href="/ciclos", key=f"cycle:deadline:actor:{suffix}")


def cycle_reopened(actor: User, cycle: WeeklyCycle) -> None:
    suffix = f"{cycle.id}:{cycle.updated_at.isoformat()}"
    notify(actor, kind="conclusao", message=f'Ciclo "{cycle.label}" reaberto.',
           href="/ciclos", key=f"cycle:reopened:actor:{suffix}")
    notify_managers(
        kind="ciclo",
        message=f'O ciclo "{cycle.label}" foi reaberto. Novo prazo: {deadline_label(cycle.deadline)}.',
        href="/relatos/novo", key=f"cycle:reopened:{suffix}",
    )


def cycle_changed(actor: User, cycle: WeeklyCycle, previous: dict | None) -> None:
    if not previous and cycle.status == CollectionStatus.OPEN:
        cycle_opened(actor, cycle)
    elif previous and previous["status"] != cycle.status:
        if cycle.status == CollectionStatus.REOPENED:
            cycle_reopened(actor, cycle)
        elif cycle.status == CollectionStatus.CLOSED:
            cycle_closed(actor, cycle)
        elif cycle.status == CollectionStatus.OPEN:
            cycle_opened(actor, cycle)
    elif previous and previous["deadline"] != cycle.deadline:
        cycle_deadline_updated(actor, cycle)


def draft_generated(actor: User, report: WeeklyReport) -> None:
    notify(
        actor, kind="conclusao", message=f'Rascunho do relatório de "{report.cycle.label}" gerado.',
        href="/relatorio-semanal", key=f"report:draft:{report.id}",
    )


def pdf_generated(actor: User, version: ReportVersion) -> None:
    notify(
        actor, kind="conclusao",
        message=(
            f'PDF do relatório de "{version.weekly_report.cycle.label}" '
            f'(versão {version.version}) gerado.'
        ),
        href="/historico", key=f"report:pdf:{version.id}",
    )


def ensure_deadline_reminders(user: User) -> None:
    now = timezone.now()
    cycles = WeeklyCycle.objects.filter(status__in=(CollectionStatus.OPEN, CollectionStatus.REOPENED))
    for cycle in cycles:
        if user.role == UserRole.MANAGER and not ActivityReport.objects.filter(
            cycle=cycle, manager=user
        ).exists():
            event = "opened" if cycle.status == CollectionStatus.OPEN else "reopened"
            already_announced = Notification.objects.filter(
                user=user, dedupe_key__startswith=f"cycle:{event}:{cycle.id}:"
            ).exists()
            if not already_announced:
                notify(
                    user, kind="ciclo",
                    message=(
                        f'O ciclo "{cycle.label}" está aberto. '
                        f'Prazo previsto: {deadline_label(cycle.deadline)}.'
                    ),
                    href="/relatos/novo",
                    key=f"cycle:current:{cycle.id}:{cycle.status}",
                )
        if not now < cycle.deadline <= now + timedelta(hours=24):
            continue
        if user.role == UserRole.MANAGER:
            if ActivityReport.objects.filter(cycle=cycle, manager=user).exists():
                continue
            message = (
                f'O prazo para enviar seu relato de "{cycle.label}" termina '
                f'em {deadline_label(cycle.deadline)}.'
            )
            href = "/relatos/novo"
        elif user.role in (UserRole.EDITOR, UserRole.ADMIN):
            pending = User.objects.filter(role=UserRole.MANAGER, active=True).exclude(
                id__in=ActivityReport.objects.filter(cycle=cycle).values("manager_id")
            ).count()
            if not pending:
                continue
            message = (
                f'O prazo de "{cycle.label}" termina em {deadline_label(cycle.deadline)}; '
                f'{pending} gestor(es) ainda não enviaram relato.'
            )
            href = "/"
        else:
            continue
        notify(
            user,
            kind="prazo",
            message=message,
            href=href,
            key=f"deadline:{cycle.id}:{cycle.deadline.isoformat()}",
        )
