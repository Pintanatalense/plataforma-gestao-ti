import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { Asset, AssetMovement, AssetService } from '../../../core/services/asset.service';
import { Employee, OrganizationService, Unit } from '../../../core/services/organization.service';
import { AttachmentsComponent } from '../../../shared/components/attachments/attachments.component';

@Component({
  selector: 'app-asset-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTabsModule,
    MatButtonModule,
    MatIconModule,
    AttachmentsComponent
  ],
  templateUrl: './asset-detail.component.html',
  styleUrls: ['./asset-detail.component.scss']
})
export class AssetDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private assetService = inject(AssetService);
  private orgService = inject(OrganizationService);

  asset: Asset | null = null;
  movements: AssetMovement[] = [];
  specEntries: [string, any][] = [];

  units: Unit[] = [];
  employees: Employee[] = [];

  ngOnInit(): void {
    const assetId = this.route.snapshot.paramMap.get('id');
    if (assetId) {
      this.loadAsset(assetId);
      this.loadMovements(assetId);
    }
    this.loadDependencies();
  }

  loadAsset(id: string): void {
    this.assetService.getAsset(id).subscribe({
      next: (asset) => {
        this.asset = asset;
        this.specEntries = asset.technical_specs ? Object.entries(asset.technical_specs) : [];
      },
      error: (err) => console.error('Erro ao carregar ativo:', err)
    });
  }

  loadMovements(id: string): void {
    this.assetService.getMovementsByAsset(id).subscribe({
      next: (movs) => (this.movements = movs),
      error: (err) => console.error('Erro ao carregar movimentações:', err)
    });
  }

  loadDependencies(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => (this.units = units),
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });

    this.orgService.getEmployees().subscribe({
      next: (emps) => (this.employees = emps),
      error: (err) => console.error('Erro ao carregar colaboradores:', err)
    });
  }

  getUnitName(unitId?: string): string {
    if (!unitId) return 'N/A';
    const found = this.units.find((u) => u.id === unitId);
    return found ? found.name : 'N/A';
  }

  getEmployeeName(employeeId?: string | null): string {
    if (!employeeId) return 'Nenhum (Em Estoque)';
    const found = this.employees.find((e) => e.id === employeeId);
    return found ? `${found.name} (${found.registration})` : 'Colaborador';
  }
}
