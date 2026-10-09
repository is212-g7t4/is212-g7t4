-- Self-referential "reports to" hierarchy on user_service, so an Event
-- Coordinator manager (manager_id is null) can be distinguished from the
-- coordinators who report to them.

alter table public.user_service
    add column manager_id uuid null;

alter table public.user_service
    add constraint user_service_manager_id_fkey
    foreign key (manager_id) references public.user_service (user_id);

create index if not exists user_service_manager_id_idx
    on public.user_service (manager_id);
