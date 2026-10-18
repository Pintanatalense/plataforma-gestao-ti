import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideRouter } from '@angular/router';
import { AdminComponent } from './admin.component';

describe('AdminComponent', () => {
  let component: AdminComponent;
  let fixture: ComponentFixture<AdminComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AdminComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideAnimationsAsync(),
        provideRouter([])
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AdminComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start on tab 0 and initialize default configs', () => {
    expect(component.activeTabIndex).toBe(0);
    expect(component.waActiveSubTab).toBe('templates'); // o canal WhatsApp saiu daqui (ADR-013 fase D)
    expect(component.importStep).toBe(1);
    expect(component.exportEntity).toBe('tickets');
  });

  it('no longer carries the legacy WhatsApp bot, anti-ban or outbox state', () => {
    const legacy = ['waConfig', 'outboxItems', 'outboxStats', 'qrData', 'waIntegrationStatus', 'togglingKillSwitch'];
    for (const key of legacy) {
      expect(key in component).toBe(false);
    }
  });

  it('should format bytes cleanly', () => {
    expect(component.formatBytes(0)).toBe('0 B');
    expect(component.formatBytes(1024)).toBe('1 KB');
    expect(component.formatBytes(1048576)).toBe('1 MB');
  });
});
