import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { signal } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { PushService, PushState, urlBase64ToBytes } from '../../../core/services/push.service';
import { PushSettingsComponent } from './push-settings.component';

function fakeService(initial: PushState) {
  return {
    state: signal<PushState>(initial),
    devices: signal(1),
    refresh: vi.fn().mockResolvedValue(undefined),
    enable: vi.fn().mockResolvedValue(undefined),
    disable: vi.fn().mockResolvedValue(undefined),
    test: vi.fn().mockResolvedValue({})
  };
}

// Aviso falso: o MatSnackBar real fica aberto 3 s e o whenStable espera ele fechar (teste lento e instável).
let snack: { open: ReturnType<typeof vi.fn> };

async function mount(service: ReturnType<typeof fakeService>) {
  snack = { open: vi.fn() };
  TestBed.configureTestingModule({
    imports: [PushSettingsComponent],
    providers: [
      provideAnimationsAsync(),
      { provide: PushService, useValue: service }
    ]
  });
  // overrideProvider: o MatSnackBarModule importado pelo componente traria o serviço real
  TestBed.overrideProvider(MatSnackBar, { useValue: snack });
  await TestBed.compileComponents();
  const fixture = TestBed.createComponent(PushSettingsComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

const q = (f: { nativeElement: HTMLElement }, id: string) => f.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe('urlBase64ToBytes', () => {
  it('decodes base64url with and without padding', () => {
    expect(Array.from(urlBase64ToBytes('AQID'))).toEqual([1, 2, 3]);
    expect(Array.from(urlBase64ToBytes('-_8'))).toEqual([251, 255]);
  });
});

describe('PushSettingsComponent', () => {
  it('offers to enable when off, and refreshes the state on open', async () => {
    const svc = fakeService('off');
    const fixture = await mount(svc);
    expect(svc.refresh).toHaveBeenCalled();
    expect(q(fixture, 'push-enable')).not.toBeNull();
    expect(q(fixture, 'push-test')).toBeNull();
  });

  it('explains why it cannot work: no HTTPS, unsupported, permission denied', async () => {
    for (const [state, id] of [['insecure', 'push-insecure'], ['unsupported', 'push-unsupported'], ['denied', 'push-denied']] as const) {
      TestBed.resetTestingModule();
      const fixture = await mount(fakeService(state));
      expect(q(fixture, id)).not.toBeNull();
      expect(q(fixture, 'push-enable')).toBeNull();
    }
  });

  it('shows test and disable when active, with the device count', async () => {
    const svc = fakeService('on');
    const fixture = await mount(svc);
    expect(fixture.nativeElement.textContent).toContain('1 aparelho');
    q(fixture, 'push-test')!.click();
    q(fixture, 'push-disable')!.click();
    await fixture.whenStable();
    expect(svc.test).toHaveBeenCalled();
    expect(svc.disable).toHaveBeenCalled();
    expect(snack.open).toHaveBeenCalledTimes(2);
  });

  it('enables on click and shows the failure message when the user refuses', async () => {
    const svc = fakeService('off');
    const fixture = await mount(svc);
    q(fixture, 'push-enable')!.click();
    await fixture.whenStable();
    expect(svc.enable).toHaveBeenCalled();
    expect(snack.open).toHaveBeenCalledTimes(1);

    svc.enable.mockRejectedValueOnce(new Error('A permissão de notificações não foi concedida.'));
    await fixture.componentInstance.enable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('permissão');
    expect(fixture.componentInstance.busy()).toBe(false);
  });

  it('prefers the server message on API errors (e.g. device limit)', async () => {
    const svc = fakeService('off');
    const fixture = await mount(svc);
    svc.enable.mockRejectedValueOnce({ error: { error: { message: 'Limite de 10 navegadores por conta.' } } });
    await fixture.componentInstance.enable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('Limite de 10');
  });
});
