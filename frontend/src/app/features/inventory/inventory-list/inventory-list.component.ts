import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { InventoryAudit, InventoryService } from '../../../core/services/inventory.service';
import { OrganizationService, Unit } from '../../../core/services/organization.service';
import { CreateAuditDialogComponent } from './create-audit-dialog.component';

@Component({
  selector: 'app-inventory-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  templateUrl: './inventory-list.component.html',
  styleUrls: ['./inventory-list.component.scss']
})
export class InventoryListComponent implements OnInit {
  private inventoryService = inject(InventoryService);
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  displayedColumns: string[] = ['name', 'unit', 'status', 'dates', 'actions'];
  dataSource = new MatTableDataSource<InventoryAudit>([]);
  units: Unit[] = [];

  ngOnInit(): void {
    this.loadUnits();
    this.loadAudits();
  }

  loadUnits(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => (this.units = units),
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });
  }

  loadAudits(): void {
    this.inventoryService.listAudits().subscribe({
      next: (audits) => {
        this.dataSource.data = audits;
        this.dataSource.filterPredicate = (data: InventoryAudit, filter: string) => {
          const unit = this.getUnitName(data.unit_id);
          const search = `${data.name} ${unit} ${data.status}`.toLowerCase();
          return search.includes(filter);
        };
      },
      error: (err) => console.error('Erro ao listar inventários:', err)
    });
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();
  }

  getUnitName(unitId: string): string {
    const u = this.units.find((x) => x.id === unitId);
    return u ? u.name : 'N/A';
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'OPENED':
        return 'chip-opened';
      case 'IN_PROGRESS':
        return 'chip-progress';
      case 'CLOSED':
        return 'chip-closed';
      case 'CANCELLED':
        return 'chip-cancelled';
      default:
        return 'chip-default';
    }
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'OPENED':
        return 'schedule';
      case 'IN_PROGRESS':
        return 'sync';
      case 'CLOSED':
        return 'check_circle';
      case 'CANCELLED':
        return 'cancel';
      default:
        return 'help_outline';
    }
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'OPENED':
        return 'Aberto';
      case 'IN_PROGRESS':
        return 'Em Andamento';
      case 'CLOSED':
        return 'Concluído';
      case 'CANCELLED':
        return 'Cancelado';
      default:
        return status;
    }
  }

  openCreateAuditDialog(): void {
    const ref = this.dialog.open(CreateAuditDialogComponent, {
      width: '450px'
    });

    ref.afterClosed().subscribe((res) => {
      if (res) {
        this.inventoryService.createAudit(res).subscribe({
          next: () => {
            this.snackBar.open('Auditoria criada com sucesso!', 'Fechar', { duration: 3000 });
            this.loadAudits();
          },
          error: (err) => {
            console.error('Erro ao criar auditoria:', err);
            const msg = err?.error?.detail || 'Erro ao criar auditoria.';
            this.snackBar.open(msg, 'Fechar', { duration: 5000 });
          }
        });
      }
    });
  }
}
