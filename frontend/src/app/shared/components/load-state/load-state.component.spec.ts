import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { LoadStateComponent } from './load-state.component';

@Component({
  standalone: true,
  imports: [LoadStateComponent],
  template: `
    <app-load-state
      [loading]="loading()"
      [error]="error()"
      [empty]="empty()"
      emptyText="Nenhum item."
      (retry)="retries = retries + 1"
    >
      <p data-testid="content">conteúdo</p>
    </app-load-state>
  `
})
class HostComponent {
  loading = signal(false);
  error = signal<string | null>(null);
  empty = signal(false);
  retries = 0;
}

describe('LoadStateComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;
  const q = (id: string) => fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HostComponent], providers: [provideAnimationsAsync()] }).compileComponents();
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('shows the content when there is nothing special', () => {
    expect(q('content')).toBeTruthy();
    expect(q('state-loading') || q('state-error') || q('state-empty')).toBeNull();
  });

  it('shows the spinner while loading, hiding content', () => {
    host.loading.set(true);
    fixture.detectChanges();
    expect(q('state-loading')).toBeTruthy();
    expect(q('content')).toBeNull();
  });

  it('shows the error with a retry button, and a failure is never rendered as an empty list', () => {
    host.error.set('Sem conexão com o servidor.');
    host.empty.set(true); // lista "vazia" porque a chamada falhou
    fixture.detectChanges();
    expect(q('state-error')?.textContent).toContain('Sem conexão com o servidor.');
    expect(q('state-empty')).toBeNull();
    expect(q('content')).toBeNull();
  });

  it('emits retry when the button is clicked', () => {
    host.error.set('Falhou');
    fixture.detectChanges();
    q('state-retry')!.click();
    expect(host.retries).toBe(1);
  });

  it('shows the empty message only when the call succeeded and brought nothing', () => {
    host.empty.set(true);
    fixture.detectChanges();
    expect(q('state-empty')?.textContent).toContain('Nenhum item.');
    expect(q('state-error')).toBeNull();
  });

  it('gives precedence to loading over error', () => {
    host.loading.set(true);
    host.error.set('x');
    fixture.detectChanges();
    expect(q('state-loading')).toBeTruthy();
    expect(q('state-error')).toBeNull();
  });
});
