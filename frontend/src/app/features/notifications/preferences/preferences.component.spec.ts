import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { NotificationPrefs, NotificationsService } from '../../../core/services/notifications.service';
import { PreferencesComponent, toggleDisabled } from './preferences.component';

const PREFS: NotificationPrefs = {
  channels_disabled: [],
  categories_disabled: [],
  quiet_enabled: true,
  quiet_start: '20:00',
  quiet_end: '07:00',
  critical_bypass: true,
  timezone: 'America/Fortaleza',
  available_channels: ['email'],
  available_categories: ['ticket', 'asset', 'stock', 'system']
};

describe('toggleDisabled', () => {
  it('keeps the list of DISABLED items consistent', () => {
    expect(toggleDisabled([], 'email', false)).toEqual(['email']);
    expect(toggleDisabled(['email'], 'email', false)).toEqual(['email']);
    expect(toggleDisabled(['email', 'x'], 'email', true)).toEqual(['x']);
    expect(toggleDisabled(['b'], 'a', false)).toEqual(['a', 'b']);
  });
});

describe('PreferencesComponent', () => {
  let fixture: ComponentFixture<PreferencesComponent>;
  let component: PreferencesComponent;
  let service: { myChannels: ReturnType<typeof vi.fn>; getPrefs: ReturnType<typeof vi.fn>; savePrefs: ReturnType<typeof vi.fn> };

  async function create(getResult = of({ ...PREFS })) {
    service = {
      myChannels: vi.fn().mockReturnValue(of({ channels: [] })),
      getPrefs: vi.fn().mockReturnValue(getResult),
      savePrefs: vi.fn().mockImplementation((p: NotificationPrefs) => of(p))
    };
    await TestBed.configureTestingModule({
      imports: [PreferencesComponent],
      providers: [provideRouter([]), provideAnimationsAsync(), { provide: NotificationsService, useValue: service }]
    }).compileComponents();
    fixture = TestBed.createComponent(PreferencesComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('loads the preferences and shows the timezone', async () => {
    await create();
    expect(component.prefs()?.quiet_start).toBe('20:00');
    expect(fixture.nativeElement.textContent).toContain('America/Fortaleza');
    expect(fixture.nativeElement.querySelector('[data-testid="channel-email"]')).toBeTruthy();
    expect(fixture.nativeElement.querySelectorAll('[data-testid^="category-"]')).toHaveLength(4);
  });

  it('reports a load failure', async () => {
    await create(throwError(() => new Error('x')) as never);
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('Não foi possível carregar');
  });

  it('saves the channel and category choices', async () => {
    await create();
    component.setChannel('email', false);
    component.setCategory('stock', false);
    component.save();
    const sent = service.savePrefs.mock.calls[0][0] as NotificationPrefs;
    expect(sent.channels_disabled).toEqual(['email']);
    expect(sent.categories_disabled).toEqual(['stock']);
  });

  it('rejects an invalid quiet window before calling the API', async () => {
    await create();
    component.prefs()!.quiet_start = '25:61';
    component.save();
    expect(service.savePrefs).not.toHaveBeenCalled();
    expect(component.error()).toContain('HH:MM');
  });

  it('accepts any times when the quiet window is turned off', async () => {
    await create();
    const p = component.prefs()!;
    p.quiet_enabled = false;
    p.quiet_start = '';
    component.save();
    expect(service.savePrefs).toHaveBeenCalled();
  });

  it('shows the server error when saving fails', async () => {
    await create();
    service.savePrefs.mockReturnValue(throwError(() => new Error('422')));
    component.save();
    expect(component.error()).toContain('Não foi possível salvar');
    expect(component.saving()).toBe(false);
  });
});
