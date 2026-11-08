-- ============================================================
--  Buzón de órdenes entre la app del móvil y el Jarvis del PC
--  La app (usuario con sesión) inserta filas «pendiente».
--  El PC (service role, se salta RLS) las ejecuta y escribe estado y respuesta.
-- ============================================================

create table public.comandos (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  texto       text not null check (char_length(texto) between 1 and 2000),
  estado      text not null default 'pendiente'
              check (estado in ('pendiente', 'ejecutando', 'confirmar', 'hecho', 'error')),
  respuesta   text,                               -- lo que contesta Jarvis (o su pregunta si estado = confirmar)
  acciones    jsonb not null default '[]'::jsonb, -- [{label, detail, status}] lo que ha ejecutado en el PC
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- El PC busca las pendientes por orden de llegada; la app lista las suyas de la más nueva a la más vieja
create index comandos_pendientes_idx on public.comandos (created_at) where estado = 'pendiente';
create index comandos_usuario_idx on public.comandos (user_id, created_at desc);

-- updated_at se pone solo en cada cambio
create function public.tocar_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger comandos_updated_at before update on public.comandos
for each row execute function public.tocar_updated_at();

-- ---------- Seguridad (RLS) ----------
alter table public.comandos enable row level security;

-- Nadie sin sesión toca la tabla (ni siquiera la ve)
revoke all on public.comandos from anon;
-- Con sesión: solo leer e insertar. Actualizar y borrar solo lo hace el PC (service role).
revoke all on public.comandos from authenticated;
grant select, insert on public.comandos to authenticated;

create policy "leo mis comandos" on public.comandos
  for select to authenticated
  using ((select auth.uid()) = user_id);

-- Solo puedo crear órdenes mías, nuevas y sin respuesta (no puedo fingir que el PC ya contestó)
create policy "creo mis comandos" on public.comandos
  for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and estado = 'pendiente'
    and respuesta is null
    and acciones = '[]'::jsonb
  );

-- ---------- Realtime ----------
alter publication supabase_realtime add table public.comandos;
