import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { InventoryAudit, InventoryAuditItem, InventoryService } from '../../../core/services/inventory.service';
import { OrganizationService } from '../../../core/services/organization.service';
import { Asset, AssetService } from '../../../core/services/asset.service';
import { StockItem, StockService } from '../../../core/services/stock.service';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';

@Component({
  selector: 'app-inventory-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './inventory-detail.component.html',
  styleUrls: ['./inventory-detail.component.scss']
})
export class InventoryDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private cdr = inject(ChangeDetectorRef);
  private fb = inject(FormBuilder);
  private inventoryService = inject(InventoryService);
  private orgService = inject(OrganizationService);
  private assetService = inject(AssetService);
  private stockService = inject(StockService);
  private snackBar = inject(MatSnackBar);

  audit: InventoryAudit | null = null;
  auditId: string | null = null;
  loadError: string | null = null;
  unitName: string = '';
  auditorName: string = '';
  populatingItems = false;

  displayedColumns: string[] = ['item', 'expected', 'actual', 'notes', 'status_result'];
  itemsDataSource = new MatTableDataSource<InventoryAuditItem>([]);

  showAddForm = false;
  availableAssets: Asset[] = [];
  availableStockItems: StockItem[] = [];

  addItemForm = this.fb.group({
    item_type: ['ASSET', Validators.required],
    asset_id: [null as string | null],
    stock_item_id: [null as string | null],
    actual_status: ['IN_STOCK'],
    actual_quantity: [1],
    notes: ['']
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.auditId = id;
      this.loadAudit(id);
    } else {
      this.loadError = 'Identificador da auditoria inválido.';
    }
  }

  retryLoad(): void {
    if (this.auditId) this.loadAudit(this.auditId);
  }

  loadAudit(id: string): void {
    this.loadError = null;
    this.inventoryService.getAudit(id).subscribe({
      next: (audit) => {
        this.audit = audit;
        this.cdr.markForCheck();
        this.itemsDataSource.data = audit.items || [];
        if (audit.unit_name) this.unitName = audit.unit_name;
        if (audit.auditor_name) this.auditorName = audit.auditor_name;
        this.loadUnitAndAuditor(audit.unit_id, audit.auditor_id);
        this.loadAvailableItems(audit.unit_id);
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Não foi possível carregar a auditoria.');
        if (this.audit) {
          // recarga depois de uma ação (iniciar, encerrar, adicionar item): mantém a tela e só avisa
          this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        } else {
          this.loadError = msg; // carga inicial (antes: tela em branco)
        }
        this.cdr.markForCheck();
      }
    });
  }

  loadUnitAndAuditor(unitId: string, auditorId: string): void {
    if (!this.unitName) {
      this.orgService.getUnits().subscribe({
        next: (units) => {
          const u = units.find((x) => x.id === unitId);
          if (u) this.unitName = u.name;
          this.cdr.markForCheck();
        }
      });
    }

    if (!this.auditorName) {
      this.orgService.getEmployees().subscribe({
        next: (emps) => {
          const e = emps.find((x) => x.id === auditorId);
          if (e) this.auditorName = `${e.name} (${e.registration_number || e.registration || ''})`;
          this.cdr.markForCheck();
        }
      });
    }
  }

  loadAvailableItems(unitId: string): void {
    this.assetService.getAssets(unitId).subscribe({
      next: (assets) => {
        this.availableAssets = assets;
        this.cdr.markForCheck();
      }
    });

    this.stockService.getItems(unitId).subscribe({
      next: (stock) => {
        this.availableStockItems = stock;
        this.cdr.markForCheck();
      }
    });
  }

  openAddItemForm(): void {
    this.showAddForm = !this.showAddForm;
  }

  onAddItemSubmit(): void {
    if (this.addItemForm.invalid || !this.audit) return;

    const val = this.addItemForm.value;
    let expectedStatus: string | null = null;
    let expectedQuantity: number | null = null;

    if (val.item_type === 'ASSET' && val.asset_id) {
      const asset = this.availableAssets.find((a) => a.id === val.asset_id);
      if (asset) expectedStatus = asset.status;
    } else if (val.item_type === 'STOCK' && val.stock_item_id) {
      const stock = this.availableStockItems.find((s) => s.id === val.stock_item_id);
      if (stock) expectedQuantity = stock.quantity;
    }

    const payload: Partial<InventoryAuditItem> = {
      audit_id: this.audit.id,
      item_type: val.item_type as 'ASSET' | 'STOCK',
      asset_id: val.asset_id,
      stock_item_id: val.stock_item_id,
      expected_status: expectedStatus,
      expected_quantity: expectedQuantity,
      actual_status: val.actual_status,
      actual_quantity: val.actual_quantity,
      notes: val.notes
    };

    this.inventoryService.addItem(this.audit.id, payload).subscribe({
      next: () => {
        this.snackBar.open('Item registrado com sucesso!', 'Fechar', { duration: 3000 });
        this.showAddForm = false;
        this.addItemForm.reset({ item_type: 'ASSET', actual_status: 'IN_STOCK', actual_quantity: 1 });
        this.loadAudit(this.audit!.id);
      },
      error: (err) => {
        console.error('Erro ao adicionar item:', err);
        const msg = apiErrorMessage(err, 'Erro ao registrar item.');
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
      }
    });
  }

  startAudit(): void {
    if (!this.audit) return;
    this.inventoryService.updateAudit(this.audit.id, { status: 'IN_PROGRESS' }).subscribe({
      next: () => {
        this.snackBar.open('Auditoria iniciada!', 'Fechar', { duration: 3000 });
        this.loadAudit(this.audit!.id);
      }
    });
  }

  closeAudit(): void {
    if (!this.audit) return;
    if (confirm('Tem certeza de que deseja finalizar e encerrar esta auditoria?')) {
      this.inventoryService.updateAudit(this.audit.id, { status: 'CLOSED' }).subscribe({
        next: () => {
          this.snackBar.open('Auditoria concluída com sucesso!', 'Fechar', { duration: 3000 });
          this.loadAudit(this.audit!.id);
        }
      });
    }
  }

  cancelAudit(): void {
    if (!this.audit) return;
    if (confirm('Deseja cancelar esta auditoria?')) {
      this.inventoryService.updateAudit(this.audit.id, { status: 'CANCELLED' }).subscribe({
        next: () => {
          this.snackBar.open('Auditoria cancelada.', 'Fechar', { duration: 3000 });
          this.loadAudit(this.audit!.id);
        }
      });
    }
  }

  populateItems(): void {
    if (!this.audit) return;
    this.populatingItems = true;
    this.inventoryService.populateItems(this.audit.id).subscribe({
      next: (updatedAudit) => {
        this.populatingItems = false;
        this.audit = updatedAudit;
        this.cdr.markForCheck();
        this.itemsDataSource.data = updatedAudit.items || [];
        if (updatedAudit.unit_name) this.unitName = updatedAudit.unit_name;
        if (updatedAudit.auditor_name) this.auditorName = updatedAudit.auditor_name;
        const count = updatedAudit.items?.length || 0;
        this.snackBar.open(`Itens da unidade sincronizados com sucesso (${count} itens carregados).`, 'OK', { duration: 4000 });
      },
      error: (err) => {
        this.populatingItems = false;
        this.cdr.markForCheck();
        this.snackBar.open(apiErrorMessage(err, 'Erro ao sincronizar itens da unidade.'), 'Fechar', { duration: 5000 });
      }
    });
  }

  getItemLabel(item: InventoryAuditItem): string {
    if (item.item_name) {
      return item.item_code ? `[${item.item_code}] ${item.item_name}` : item.item_name;
    }
    if (item.item_type === 'ASSET') {
      const asset = this.availableAssets.find((a) => a.id === item.asset_id);
      return asset ? `[${asset.tag}] ${asset.name}` : `Ativo #${item.asset_id?.slice(0, 8)}`;
    } else {
      const stock = this.availableStockItems.find((s) => s.id === item.stock_item_id);
      return stock ? stock.name : `Insumo #${item.stock_item_id?.slice(0, 8)}`;
    }
  }

  isCompliant(item: InventoryAuditItem): boolean {
    if (item.item_type === 'ASSET') {
      return item.actual_status === item.expected_status;
    } else {
      return item.actual_quantity === item.expected_quantity;
    }
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
}
