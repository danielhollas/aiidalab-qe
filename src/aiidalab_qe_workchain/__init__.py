# AiiDA imports.
from aiida.common import AttributeDict
from aiida.engine import ToContext, WorkChain, if_
from aiida.orm import CalcJobNode, WorkChainNode
from aiida.plugins import DataFactory, WorkflowFactory

# AiiDA Quantum ESPRESSO plugin inputs.
from aiida_quantumespresso.common.types import RelaxType
from aiida_quantumespresso.utils.mapping import prepare_process_inputs

# Data objects and work chains.
PwRelaxWorkChain = WorkflowFactory("quantumespresso.pw.relax")
PwBandsWorkChain = WorkflowFactory("quantumespresso.pw.bands")
PdosWorkChain = WorkflowFactory("quantumespresso.pdos")

Bool = DataFactory("core.bool")
Float = DataFactory("core.float")
Dict = DataFactory("core.dict")
Str = DataFactory("core.str")
XyData = DataFactory("core.array.xy")
StructureData = DataFactory("core.structure")
BandsData = DataFactory("core.array.bands")
Orbital = DataFactory("core.orbital")


class QeAppWorkChain(WorkChain):
    """WorkChain designed to calculate the requested properties in the AiiDAlab Quantum ESPRESSO app."""

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        # yapf: disable
        super().define(spec)
        spec.input('structure', valid_type=StructureData,
                   help='The inputs structure.')
        spec.input('clean_workdir', valid_type=Bool, default=lambda: Bool(False),
                   help='If `True`, work directories of all called calculation will be cleaned at the end of execution.')
        spec.expose_inputs(PwRelaxWorkChain, namespace='relax', exclude=('clean_workdir', 'structure'),
                           namespace_options={'required': False, 'populate_defaults': False,
                                              'help': 'Inputs for the `PwRelaxWorkChain`, if not specified at all, the relaxation step is skipped.'})
        spec.expose_inputs(PwBandsWorkChain, namespace='bands',
                           exclude=('clean_workdir', 'structure', 'relax'),
                           namespace_options={'required': False, 'populate_defaults': False,
                                              'help': 'Inputs for the `PwBandsWorkChain`.'})
        spec.expose_inputs(PdosWorkChain, namespace='pdos',
                           exclude=('clean_workdir', 'structure'),
                           namespace_options={'required': False, 'populate_defaults': False,
                                              'help': 'Inputs for the `PdosWorkChain`.'})
        spec.input(
            'kpoints_distance_override', valid_type=Float, required=False,
            help='Override for the kpoints distance value of all `PwBaseWorkChains` except for the `nscf` calculations.'
        )
        spec.input(
            'degauss_override', valid_type=Float, required=False,
            help='Override for the `degauss` value of all `PwBaseWorkChains` except for the `nscf` calculations.'
        )
        spec.input(
            'smearing_override', valid_type=Str, required=False,
            help='Override for the `smearing` value of all `PwBaseWorkChains` save for the `nscf` calculations.'
        )
        spec.outline(
            cls.setup,
            if_(cls.should_run_relax)(
                cls.run_relax,
                cls.inspect_relax
            ),
            if_(cls.should_run_bands)(
                cls.run_bands,
                cls.inspect_bands
            ),
            if_(cls.should_run_pdos)(
                cls.run_pdos,
                cls.inspect_pdos
            ),
            cls.results
        )
        spec.exit_code(401, 'ERROR_SUB_PROCESS_FAILED_RELAX',
                       message='The PwRelaxWorkChain sub process failed')
        spec.exit_code(403, 'ERROR_SUB_PROCESS_FAILED_BANDS',
                       message='The PwBandsWorkChain sub process failed')
        spec.exit_code(404, 'ERROR_SUB_PROCESS_FAILED_PDOS',
                       message='The PdosWorkChain sub process failed')
        spec.output('structure', valid_type=StructureData, required=False)
        spec.output('band_parameters', valid_type=Dict, required=False)
        spec.output('band_structure', valid_type=BandsData, required=False)
        spec.output('nscf_parameters', valid_type=Dict, required=False)
        spec.output('dos', valid_type=XyData, required=False)
        spec.output('projections', valid_type=Orbital, required=False)
        spec.output('projections_up', valid_type=Orbital, required=False)
        spec.output('projections_down', valid_type=Orbital, required=False)
        # yapf: enable

    @classmethod
    def get_builder_from_protocol(
        cls,
        structure,
        pw_code,
        dos_code=None,
        projwfc_code=None,
        protocol=None,
        overrides=None,
        relax_type=RelaxType.NONE,
        pseudo_family=None,
        **kwargs,
    ):
        """Return a builder prepopulated with inputs selected according to the chosen protocol."""
        overrides = overrides or {}
        builder = cls.get_builder()
        builder.structure = structure

        relax_overrides = overrides.get("relax", {})
        if pseudo_family is not None:
            relax_overrides.setdefault("base", {})["pseudo_family"] = pseudo_family

        relax = PwRelaxWorkChain.get_builder_from_protocol(
            code=pw_code,
            structure=structure,
            protocol=protocol,
            overrides=relax_overrides,
            relax_type=relax_type,
            **kwargs,
        )
        relax.pop("structure", None)
        relax.pop("clean_workdir", None)
        relax.pop("base_final_scf", None)
        builder.relax = relax

        bands_overrides = overrides.get("bands", {})
        if pseudo_family is not None:
            bands_overrides.setdefault("scf", {})["pseudo_family"] = pseudo_family
            bands_overrides.setdefault("bands", {})["pseudo_family"] = pseudo_family
        bands = PwBandsWorkChain.get_builder_from_protocol(
            code=pw_code,
            structure=structure,
            protocol=protocol,
            overrides=bands_overrides,
            **kwargs,
        )
        bands.pop("relax")
        bands.pop("structure", None)
        bands.pop("clean_workdir", None)
        builder.bands = bands

        if dos_code is not None and projwfc_code is not None:
            pdos_overrides = overrides.get("pdos", {})
            if pseudo_family is not None:
                pdos_overrides.setdefault("scf", {})["pseudo_family"] = pseudo_family
                pdos_overrides.setdefault("nscf", {})["pseudo_family"] = pseudo_family
            pdos = PdosWorkChain.get_builder_from_protocol(
                pw_code=pw_code,
                dos_code=dos_code,
                projwfc_code=projwfc_code,
                structure=structure,
                protocol=protocol,
                overrides=pdos_overrides,
                **kwargs,
            )
            pdos.pop("structure", None)
            pdos.pop("clean_workdir", None)
            builder.pdos = pdos

        builder.clean_workdir = overrides.get("clean_workdir", Bool(False))
        if "kpoints_distance_override" in overrides:
            builder.kpoints_distance_override = overrides["kpoints_distance_override"]
        if "degauss_override" in overrides:
            builder.degauss_override = overrides["degauss_override"]
        if "smearing_override" in overrides:
            builder.smearing_override = overrides["smearing_override"]

        return builder

    def setup(self):
        """Perform the initial setup of the work chain."""
        self.ctx.current_structure = self.inputs.structure
        self.ctx.current_number_of_bands = None
        self.ctx.scf_parent_folder = None

    def should_run_relax(self):
        """Check if the geometry of the input structure should be optimized."""
        return "relax" in self.inputs

    def run_relax(self):
        """Run the `PwRelaxWorkChain`."""
        inputs = AttributeDict(self.exposed_inputs(PwRelaxWorkChain, namespace="relax"))
        inputs.metadata.call_link_label = "relax"
        inputs.structure = self.ctx.current_structure

        if "kpoints_distance_override" in self.inputs:
            inputs.base.kpoints_distance = self.inputs.kpoints_distance_override
            if "base_scf" in inputs:
                inputs.base_scf.kpoints_distance = self.inputs.kpoints_distance_override

        inputs.base.pw.parameters = inputs.base.pw.parameters.get_dict()
        if "degauss_override" in self.inputs:
            inputs.base.pw.parameters.setdefault("SYSTEM", {})[
                "degauss"
            ] = self.inputs.degauss_override.value

            if "base_scf" in inputs:
                inputs.base_scf_params.pw.parameters = (
                    inputs.base_scf_params.pw.parameters.get_dict()
                )
                inputs.base_scf_params.pw.parameters.setdefault("SYSTEM", {})[
                    "degauss"
                ] = self.inputs.degauss_override.value
        if "smearing_override" in self.inputs:
            inputs.base.pw.parameters.setdefault("SYSTEM", {})[
                "smearing"
            ] = self.inputs.smearing_override.value

            if "base_scf" in inputs:
                inputs.base_scf_params.pw.parameters = (
                    inputs.base_scf_params.pw.parameters.get_dict()
                )
                inputs.base_scf_params.pw.parameters.setdefault("SYSTEM", {})[
                    "smearing"
                ] = self.inputs.smearing_override.value

        inputs = prepare_process_inputs(PwRelaxWorkChain, inputs)
        running = self.submit(PwRelaxWorkChain, **inputs)

        self.report(f"launching PwRelaxWorkChain<{running.pk}>")

        return ToContext(workchain_relax=running)

    def inspect_relax(self):
        """Verify that the `PwRelaxWorkChain` finished successfully."""
        workchain = self.ctx.workchain_relax

        if not workchain.is_finished_ok:
            self.report(
                f"PwRelaxWorkChain failed with exit status {workchain.exit_status}"
            )
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        if "output_structure" in workchain.outputs:
            self.ctx.current_structure = workchain.outputs.output_structure
            self.ctx.current_number_of_bands = (
                workchain.outputs.output_parameters.get_attribute("number_of_bands")
            )
            self.out("structure", self.ctx.current_structure)

    def should_run_bands(self):
        """Check if the band structure should be calculated."""
        return "bands" in self.inputs

    def run_bands(self):
        """Run the `PwBandsWorkChain`."""
        inputs = AttributeDict(self.exposed_inputs(PwBandsWorkChain, namespace="bands"))
        inputs.metadata.call_link_label = "bands"
        inputs.structure = self.ctx.current_structure
        inputs.scf.pw.parameters = inputs.scf.pw.parameters.get_dict()

        if self.ctx.current_number_of_bands:
            inputs.scf.pw.parameters.setdefault("SYSTEM", {}).setdefault(
                "nbnd", self.ctx.current_number_of_bands
            )

        if "kpoints_distance_override" in self.inputs:
            inputs.scf.kpoints_distance = self.inputs.kpoints_distance_override

        if "degauss_override" in self.inputs:
            inputs.scf.pw.parameters.setdefault("SYSTEM", {})[
                "degauss"
            ] = self.inputs.degauss_override.value
        if "smearing_override" in self.inputs:
            inputs.scf.pw.parameters.setdefault("SYSTEM", {})[
                "smearing"
            ] = self.inputs.smearing_override.value

        inputs = prepare_process_inputs(PwBandsWorkChain, inputs)
        running = self.submit(PwBandsWorkChain, **inputs)

        self.report(f"launching PwBandsWorkChain<{running.pk}>")

        return ToContext(workchain_bands=running)

    def inspect_bands(self):
        """Verify that the `PwBandsWorkChain` finished successfully."""
        workchain = self.ctx.workchain_bands

        if not workchain.is_finished_ok:
            self.report(
                f"PwBandsWorkChain failed with exit status {workchain.exit_status}"
            )
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_BANDS

        scf = workchain.get_outgoing(WorkChainNode, link_label_filter="scf").one().node
        self.ctx.scf_parent_folder = scf.outputs.remote_folder
        self.ctx.current_structure = workchain.outputs.primitive_structure

    def should_run_pdos(self):
        """Check if the projected density of states should be calculated."""
        return "pdos" in self.inputs

    def run_pdos(self):
        """Run the `PdosWorkChain`."""
        inputs = AttributeDict(self.exposed_inputs(PdosWorkChain, namespace="pdos"))
        inputs.metadata.call_link_label = "pdos"
        inputs.structure = self.ctx.current_structure
        inputs.nscf.pw.parameters = inputs.nscf.pw.parameters.get_dict()

        if self.ctx.current_number_of_bands:
            inputs.nscf.pw.parameters.setdefault("SYSTEM", {}).setdefault(
                "nbnd", self.ctx.current_number_of_bands
            )

        if self.ctx.scf_parent_folder:
            inputs.pop("scf")
            inputs.nscf.pw.parent_folder = self.ctx.scf_parent_folder
        else:
            if "kpoints_distance_override" in self.inputs:
                inputs.scf.kpoints_distance = self.inputs.kpoints_distance_override

            inputs.scf.pw.parameters = inputs.scf.pw.parameters.get_dict()
            if "degauss_override" in self.inputs:
                inputs.scf.pw.parameters.setdefault("SYSTEM", {})[
                    "degauss"
                ] = self.inputs.degauss_override.value

            if "smearing_override" in self.inputs:
                inputs.scf.pw.parameters.setdefault("SYSTEM", {})[
                    "smearing"
                ] = self.inputs.smearing_override.value

        inputs = prepare_process_inputs(PdosWorkChain, inputs)
        running = self.submit(PdosWorkChain, **inputs)

        self.report(f"launching PdosWorkChain<{running.pk}>")

        return ToContext(workchain_pdos=running)

    def inspect_pdos(self):
        """Verify that the `PdosWorkChain` finished successfully."""
        workchain = self.ctx.workchain_pdos

        if not workchain.is_finished_ok:
            self.report(
                f"PdosWorkChain failed with exit status {workchain.exit_status}"
            )
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_PDOS

    def results(self):
        """Add the results to the outputs."""
        if "workchain_bands" in self.ctx:
            self.out(
                "band_parameters", self.ctx.workchain_bands.outputs.band_parameters
            )
            self.out("band_structure", self.ctx.workchain_bands.outputs.band_structure)

        if "workchain_pdos" in self.ctx:
            self.out(
                "nscf_parameters",
                self.ctx.workchain_pdos.outputs.nscf.output_parameters,
            )
            self.out("dos", self.ctx.workchain_pdos.outputs.dos.output_dos)
            if "projections_up" in self.ctx.workchain_pdos.outputs.projwfc:
                self.out(
                    "projections_up",
                    self.ctx.workchain_pdos.outputs.projwfc.projections_up,
                )
                self.out(
                    "projections_down",
                    self.ctx.workchain_pdos.outputs.projwfc.projections_down,
                )
            else:
                self.out(
                    "projections", self.ctx.workchain_pdos.outputs.projwfc.projections
                )

    def on_terminated(self):
        """Clean the working directories of all child calculations if `clean_workdir=True` in the inputs."""
        super().on_terminated()

        if self.inputs.clean_workdir.value is False:
            self.report("remote folders will not be cleaned")
            return

        cleaned_calcs = []

        for called_descendant in self.node.called_descendants:
            if isinstance(called_descendant, CalcJobNode):
                try:
                    called_descendant.outputs.remote_folder._clean()  # pylint: disable=protected-access
                    cleaned_calcs.append(called_descendant.pk)
                except (OSError, KeyError):
                    pass

        if cleaned_calcs:
            self.report(
                f"cleaned remote folders of calculations: {' '.join(map(str, cleaned_calcs))}"
            )


__version__ = "23.1.0b0"
