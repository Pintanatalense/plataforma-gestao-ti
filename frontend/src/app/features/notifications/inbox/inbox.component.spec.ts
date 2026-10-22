import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { Subject, of, throwError } from 'rxjs';
import { Notification, NotificationsService } from '../../../core/services/notifications.service';
import { InboxComponent, notificationLink } from './inbox.component';

function note(id: string, over: Partial<Notification> = {}): Notification {
  return {
    id, user_id: 'u1', title: `Título ${id}`, message: 'm', type: 'info', is_read: false,
    created_at: '2026-10-17T12:00:00Z', ...over
  };
}

describe('InboxComponent', () => {
  let fixture: ComponentFixture<InboxComponent>;
  let component: InboxComponent;
  let service: {
    list: ReturnType<typeof vi.fn>;
    unreadCount: ReturnType<typeof vi.fn>;
    markAsRead: ReturnType<typeof vi.fn>;
    markAllAsRead: ReturnType<typeof vi.fn>;
    newNotification$: Subject<Notification>;
    reconnected$: Subject<void>;
  };

  async function create(items: Notification[]) {
    service = {
      list: vi.fn().mockReturnValue(of(items)),
      unreadCount: vi.fn().mockReturnValue(of({ count: items.filter((n) => !n.is_read).length })),
      markAsRead: vi.fn().mockReturnValue(of({})),
      markAllAsRead: vi.fn().mockReturnValue(of({})),
      newNotification$: new Subject<Notification>(),
      reconnected$: new Subject<void>()
    };
    await TestBed.configureTestingModule({
      imports: [InboxComponent],
      providers: [provideRouter([]), provideAnimationsAsync(), { provide: NotificationsService, useValue: service }]
    }).compileComponents();
    fixture = TestBed.createComponent(InboxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  const rows = () => fixture.nativeElement.querySelectorAll('[data-testid="notification-item"]');

  it('renders the notifications and the unread counter', async () => {
    await create([note('a'), note('b', { is_read: true })]);
    expect(rows()).toHaveLength(2);
    expect(rows()[0].classList.contains('unread')).toBe(true);
    expect(rows()[1].classList.contains('unread')).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('1 não lida(s)');
  });

  it('does not claim "no notifications" when the load failed, and a failed "load more" is reported', async () => {
    await create([]);
    service.list.mockReturnValue(throwError(() => new Error('x')));
    component.reload();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Não foi possível carregar as notificações.');
    expect(fixture.nativeElement.textContent).not.toContain('Nenhuma notificação');

    component.loadMore();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Não foi possível carregar mais notificações.');
  });

  it('shows an empty state', async () => {
    await create([]);
    expect(fixture.nativeElement.textContent).toContain('Nenhuma notificação');
  });

  it('sends the read filter to the API', async () => {
    await create([note('a')]);
    component.status = 'unread';
    component.type = 'error';
    component.reload();
    expect(service.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_read: false, type: 'error', limit: 25, offset: 0 })
    );
    component.status = 'all';
    component.reload();
    expect(service.list.mock.lastCall![0].is_read).toBeUndefined();
  });

  it('marks one notification as read without reloading the list', async () => {
    await create([note('a')]);
    component.markRead(component.items()[0]);
    expect(service.markAsRead).toHaveBeenCalledWith('a');
    expect(component.items()[0].is_read).toBe(true);
  });

  it('opens the ticket behind a notification and marks it read', async () => {
    await create([note('a', { entity_type: 'ticket', entity_id: 'T-9' })]);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    component.open(component.items()[0]);
    expect(service.markAsRead).toHaveBeenCalledWith('a');
    expect(navigate).toHaveBeenCalledWith(['/service-desk', 'T-9']);
  });

  it('reloads when a push arrives or the socket reconnects', async () => {
    await create([note('a')]);
    const calls = service.list.mock.calls.length;
    service.newNotification$.next(note('b'));
    service.reconnected$.next();
    expect(service.list.mock.calls.length).toBe(calls + 2);
  });

  it('offers "load more" only when a full page came back', async () => {
    await create(Array.from({ length: 25 }, (_, i) => note(String(i))));
    expect(component.hasMore()).toBe(true);
    service.list.mockReturnValue(of([note('x')]));
    component.loadMore();
    expect(service.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }));
    expect(component.items()).toHaveLength(26);
    expect(component.hasMore()).toBe(false);
  });

  it('surfaces a load failure instead of an empty list', async () => {
    await create([]);
    service.list.mockReturnValue(new Subject<Notification[]>());
    const failing = new Subject<Notification[]>();
    service.list.mockReturnValue(failing);
    component.reload();
    failing.error(new Error('boom'));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('Não foi possível');
  });
});

describe('notificationLink', () => {
  it('links tickets and ignores unknown entities', () => {
    expect(notificationLink({ entity_type: 'ticket', entity_id: 'x' })).toEqual(['/service-desk', 'x']);
    expect(notificationLink({ entity_type: 'backup', entity_id: undefined })).toBeNull();
    expect(notificationLink({})).toBeNull();
  });
});
